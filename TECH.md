# Technology Stack & Architecture — data-gouv-tool

`data-gouv-cli` — the French public data entry point of the fleet.
Three layers: the **data.gouv.fr catalogue**, a **SQL engine over remote
tabular files**, and a **generic JSON API caller**. TOON output only.

- Version: 0.1.0 (tool) / 0.2.0 (logic)
- Entry point: `run_data_gouv_cli.py` → `data_gouv_logic.FrenchGovTool`
- Skill: `command-line-tools/subskills/data-gouv-cli`
- Commands: 16 (`--help` is the TOON-rendered, token-lean version)

---

## 1. Technology Matrix

| Layer | Component / Library | Purpose | Pros | Limitations |
|---|---|---|---|---|
| **Catalogue** | data.gouv.fr API **v2** (`2/datasets/search/`) | dataset search | Good recall: matches loosely, does not AND every keyword | Truncates the resource list → the file URL is missing from the answer |
| **Catalogue** | data.gouv.fr API **v1** (`1/datasets/<id>/`) | full resource list with URLs, `extras` metadata | Carries `url`, `mime`, `type`, `analysis:content-length` (the size, known without downloading), `analysis:checksum` | ANDs every keyword: "pauvreté communale" returns nothing while "pauvreté" returns 13 |
| **Hydratation** | `ThreadPoolExecutor` (8 threads) | fetches the v1 details of the v2 winners in parallel | A search result carries its file URL; 1,3 s for 20 results | One HTTP call per result; a failed hydration is silently skipped (the row keeps a null URL) |
| **Requête** | `duckdb` **2.0.0** (version alignée flotte, cf. `constraints.toml`) | SQL over CSV, Parquet and JSON, local or remote | One engine for three formats; `httpfs` reads a remote file over HTTP Range, with **zero** download | **Cannot open a zip archive**: `read_csv`, `read_csv_auto`, `read_parquet` and glob all fail on the `PK` magic |
| **Accès distant** | extension DuckDB `httpfs` | HTTP Range reads on a remote table | The 1,86 GB OLAP Insee parquet answers a three-commune query in **8,7 s** with nothing downloaded | Needs Range support on the host; the extension must be installable (network) or already in `~/.duckdb/extensions` |
| **ZIP distant** | `remotezip` **0.12.6** (extra optionnel `remote`, import paresseux) | reads **one member** of a remote zip over HTTP Range | Never downloads the archive when a single member is needed | Needs a **suffix** range (`bytes=-N`): `api.insee.fr` answers 500, `www.insee.fr` ignores Range. The upstream **prefix mode is broken** (it confuses the buffer size with the file size → `BadZipFile`), so only the suffix mode is used |
| **ZIP local** | `zipfile` (stdlib) | extracts a member after a full download | Zero dependency, always available | The whole archive has to reach the disk first |
| **Formats** | `pyarrow` 26 | CSV → Parquet conversion, Parquet metadata | Conversion without DuckDB | `pyarrow.csv` is strict on French CSVs (`;` separator) |
| **Excel** | `openpyxl` 3.1, `xlrd` 2.0 | `.xlsx` / `.xls` → CSV | Both Excel formats covered | Not queryable by DuckDB: the CLI says so and points to `excel-cli` |
| **Sérialisation** | `cli_common.toon_output` + `python-toon` 0.2 | TOON tables and objects | 40-60 % fewer tokens than JSON | Nested cells are flattened to compact JSON before rendering |
| **CLI** | `typer` 0.27 + `rich` 15 | commands, options, TOON help | Type-annotated, compact help | — |
| **Réseau** | `requests` 2.34 | HTTP calls, streaming | Explicit timeouts, **full** error bodies (never sliced) | — |
| **Cache** | `~/.cache/data-gouv-cli/` | downloaded archives, extracted members | A downloaded archive is reused by the next query | No expiry policy |

---

## 2. Layer & Role

**Role in the fleet** : the only tool that reaches the French state data
(INSEE, data.gouv.fr, MELODI archives). It sits between the agent and files
that are too big to download to answer a question.

```text
COUCHE 1 — CATALOGUE : la donnée existe-t-elle, et où est le fichier ?
  search-datasets ─▶ v2 (rappel) ─▶ hydratation v1 en parallèle (URL + taille)
  resolve          ─▶ 1 appel : dataset + chaque ressource + tabular ?
  resource         ─▶ 1 ressource : url, mime, content-length, checksum
  dataset-resources─▶ les ressources d'un dataset, URL conservée
        │
        ▼
COUCHE 2 — REQUÊTE : lire la donnée sans la télécharger
  query <url|chemin|resource:<id>> --sql "select … from data"
        │
        ├── fichier local .................. DuckDB lit le fichier
        ├── distant csv/parquet/json ...... httpfs, requêtes Range, 0 téléchargement
        ├── distant zip ................... remotezip (Range suffixe) → membre extrait
        └── repli .......................... téléchargement en cache → lecture locale
        │
        ▼
COUCHE 3 — API : n'importe quel JSON
  api <url> [--param k=v] [--header k=v] [--body JSON] [--field chemin] → TOON
```

**Le SQL de `query` s'exécute contre une vue nommée `data`.** L'agent écrit
`from data`, jamais le chemin du fichier : le format (csv / parquet / json /
membre de zip) est résolu par l'outil.

**Deux règles non négociables de la couche 2** :

1. **Jamais de téléchargement par défaut.** Le chemin `httpfs_direct` est tenté
   en premier pour tout csv/parquet/json distant ; le téléchargement n'est qu'un
   repli. Chaque repli affiche **une** ligne stderr : la source, la raison
   complète, l'action entreprise. Aucun repli silencieux.
2. **Le secret statistique reste un secret.** Une valeur absente reste absente :
   le CLI ne transforme jamais un `null` en `0`. Sur FILOSOFI 2023, 5 256
   communes sont diffusables et 29 512 confidentielles (secret statistique) —
   les deux sont comptées, aucune n'est écrasée.

### Table de décision de `query`

| Source | Format détecté | Stratégie | Transfert |
|---|---|---|---|
| `/tmp/x.parquet` | parquet (extension) | local | 0 |
| `https://static.data.gouv.fr/…/olap.parquet` | parquet (magic `PAR1`) | `httpfs_direct` | quelques Mo de Range |
| `https://static.data.gouv.fr/…/carreaux.csv` | csv (magic/extension) | `httpfs_direct` | idem |
| `https://api.insee.fr/melodi/file/…_CSV_FR` | zip (magic `PK`) | `zip_range` si Range suffixe, sinon `zip_download` | 5,3 Mo (archive compressée) |
| `https://www.insee.fr/…/Filosofi2019_carreaux_200m_csv.zip` | zip (extension) | `zip_download` (Range ignoré par l'hôte) | 61,7 Mo |
| `resource:<id>` | celui de la ressource | idem | idem |

**Règle de choix du membre d'une archive** : le membre dont le nom contient
« data », et à défaut le plus gros membre de type csv/parquet/json. Le fichier
de métadonnées d'un jeu de données est toujours plus petit que son fichier de
données : la taille sépare les deux.

---

## 3. Strengths & Limitations

### Forces (mesurées)

| Capacité | Mesure |
|---|---|
| Parquet distant OLAP Insee **1,86 Go** | **8,7 s** pour la série de pauvreté de 3 communes, **0 octet téléchargé** (`httpfs_direct`) |
| Grille carroyées 200 m (95 Mo) | 2 298 582 carreaux, taux de pauvreté **15,03 %**, ~4 s |
| Zip MELODI Insee (5,3 Mo → 58 Mo de CSV) | **7,7 s**, repli téléchargement + extraction du membre |
| Contenu FILOSOFI 2023 | COM 34 768 (5 256 diffusables + 29 512 confidentiels), EPCI 1 235, UU2020 2 430, DEP 97, REG 14, FRANCE 1 |
| Recherche « pauvreté communale » | **1,3 s**, URL de fichier incluse dans le résultat |
| `resolve` d'un dataset | 1 appel au lieu de 3 (dataset → resources → resource par fichier) |
| Erreur d'API | corps **complet** affiché, sortie 1, pas de traceback |

### Limites

- **Les agrégats lourds sont lents, et c'est la donnée, pas l'outil.** Un
  `count(distinct)` sur les 1,86 Go du OLAP Insee parcourt des dizaines de
  millions de lignes et dépasse le budget de temps de l'agent. Ce qui rend la
  requête instantanée, c'est le filtre (`clef_json`, `code_com`), pas le moteur.
- **DuckDB ne lit pas les zip.** Tout zip passe par `zipfile` (local) ou
  `remotezip` (distant). Les archives Insee Carolées (61,7 Mo) seront
  téléchargées en entier, systématiquement.
- **Le Range suffixe est rare.** `static.data.gouv.fr` et `api.insee.fr`
  l'acceptent ; `www.insee.fr` ne supporte pas Range du tout et renvoie le
  corps complet à chaque requête.
- **L'API tabular de data.gouv ne couvre qu'une minorité de ressources.** Les
  parquets, les archives Insee et les CSV MELODI n'y sont pas indexés :
  `query-resource` renvoie un 404 sur ces fichiers, `query` est le chemin qui
  fonctionne. La disponibilité est **sondee**, jamais supposée.
- **Pas de jointure géographique.** `query` ne croise pas une commune avec un
  contour : le géocodage reste à la charge de l'appelant (INSEE COG,
  geo.api.gouv.fr) ou d'un script dédié.
- **Les DROM sont absents** des carroyées (`met-3035` = métropole) et de l'OLAP
  communal, comme des séries FILOSOFI locales.
- **`search-datasets` fait N+1 appels.** L'hydratation v1 est parallèle (8
  threads) mais réelle : c'est le prix du lien vers le fichier.
- **La casse et les accents comptent.** L'API v1 ne normalise pas : « pauvrete »
  renvoie 0 résultat, « pauvreté » en renvoie 13.

---

## 4. Upgrade Triggers / Replacement Criteria

1. **L'API data.gouv expose les ressources complètes dans la recherche**
   *État actuel* : v2 pour le rappel, v1 en parallèle pour les URL (N+1 appels).
   *Déclencheur* : une réponse de recherche qui porte `url` et `content_length`
   → supprimer `search_datasets._hydrate_resource_urls` et le `ThreadPoolExecutor`.

2. **DuckDB sait ouvrir un zip**
   *État actuel* : `zipfile` + `remotezip`, deux chemins de code, un bug connu
   dans le second.
   *Déclencheur* : un scanner zip natif → supprimer `_extract_remote_member`,
   `_extract_local_member` et la branche `zip_download` de
   `_prepare_zip_member`.

3. **`remotezip` est abandonné ou corrigé en amont**
   *État actuel* : extra optionnel, import paresseux, repli automatique sur le
   téléchargement.
   *Déclencheur* : le paquet n'est plus maintenu → réimplémenter la lecture du
   répertoire central par Range suffixe (~60 lignes) **dans `cli_common`**, pas
   dans l'outil : une troisième copie du même code est un défaut
   (Rule 5 de `cli-tool-packaging`).

4. **Insee republie les archives MELODI sur `static.data.gouv.fr`**
   *État actuel* : `api.insee.fr` refuse le Range suffixe (500), donc le chemin
   `zip_range` ne s'active jamais et l'archive est téléchargée.
   *Déclencheur* : une republication sur un hôte qui accepte le suffixe →
   `zip_range` s'active, le téléchargement du zip disparaît.

5. **Mesurer le gain de l'E/S asynchrone de DuckDB 2.0 sur le parquet distant**
   *État actuel* : duckdb 2.0.0, aligné sur la flotte (l'E/S asynchrone de la
   v2.0 s'applique déjà aux lectures Parquet/CSV distantes via `httpfs`).
   *Déclencheur* : un gain mesuré **> 2×** sur le scanning de colonnes
   (mesure : `EXPLAIN ANALYZE` sur le parquet 1,86 Go) par rapport aux 8,7 s
   relevés en 1.5.3.

6. **L'Insee expose des métadonnées de fichier**
   *État actuel* : la taille et le checksum sont lus dans
   `extras.analysis:*`, donc absents sur certains datasets.
   *Déclencheur* : un endpoint de métadonnées (taille, checksum, embargo) →
   remplacer la lecture de `extras` par cet endpoint et fiabiliser
   `content_length`.

7. **Une API Insee structure (non fichier) pour le local**
   *État actuel* : les URL sont des fichiers (zip, parquet, csv).
   *Déclencheur* : une API qui expose le FILOSOFI local déjà agrégé par commune
   → la couche 2 se réduit à un appel d'API et la couche 3 prend le relais.

8. **Critère de remplacement**
   Remplacer l'outil si le catalogue data.gouv cesse d'être la source la plus
   fiable pour les fichiers INSEE **et** que les API Insee (`api.insee.fr`,
   Melodi) continuent d'exposer des URL stables — autrement dit, si la couche 2
   (`query`) devient le point d'entrée principal au lieu de la couche 1.
