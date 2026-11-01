"""Cancer Basemap: population cancer data as Apache Iceberg tables."""

import os
from pathlib import Path

from pyiceberg.catalog import load_catalog


def catalog():
    """The Cancer Basemap catalog.

    Defaults to a local sqlite-backed warehouse (`./warehouse`, override with
    `CANCERBASEMAP_WAREHOUSE`) so nothing needs cloud credentials. Set
    `CANCERBASEMAP_URI` to talk to a REST catalog (icegate) instead, with
    `CANCERBASEMAP_WAREHOUSE` as the catalog name and `CANCERBASEMAP_TOKEN` as the key.
    """
    uri = os.environ.get("CANCERBASEMAP_URI")
    if uri:
        props = {"type": "rest", "uri": uri,
                 "warehouse": os.environ.get("CANCERBASEMAP_WAREHOUSE", "canceronice")}
        token = os.environ.get("CANCERBASEMAP_TOKEN")
        if token:
            props["token"] = token
        return load_catalog("canceronice", **props)

    warehouse = Path(os.environ.get("CANCERBASEMAP_WAREHOUSE", "warehouse")).absolute()
    warehouse.mkdir(parents=True, exist_ok=True)
    return load_catalog("canceronice", type="sql",
                        uri=f"sqlite:///{warehouse}/catalog.db",
                        warehouse=warehouse.as_uri())
