"""Description of this command, the only entry the public tool needs."""

_DESCRIPTION = 'french-gov-cli — Clean wrapper around the French government data.gouv.fr APIs (datasets, dataservices, orgs, resources, tabular, metrics)'


def description_for(command: str = "", fallback: str = "") -> str:
    """Return this tool's description regardless of the invoked name."""
    return _DESCRIPTION or fallback
