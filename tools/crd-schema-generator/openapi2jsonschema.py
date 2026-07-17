#!/usr/bin/env python3

import json
import os
import sys
import urllib.request

import yaml


if "DISABLE_SSL_CERT_VALIDATION" in os.environ:
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context


QUIET = os.getenv(
    "QUIET",
    "0"
).lower() in (
    "1",
    "true",
    "yes"
)


DENY_ROOT_ADDITIONAL_PROPERTIES = (
    "DENY_ROOT_ADDITIONAL_PROPERTIES"
    in os.environ
)


FILENAME_FORMAT = os.getenv(
    "FILENAME_FORMAT",
    "{kind}_{version}"
)


INT_OR_STRING_SCHEMA = {
    "oneOf": [
        {
            "type": "string"
        },
        {
            "type": "integer"
        }
    ]
}


def optimize_schema(node, is_root=False):
    """
    Optimized in-place schema transformation.

    Restores kubeconform behavior:
    - add additionalProperties:false to objects with properties
    - do not add it to root unless requested
    - replace int-or-string markers
    """

    if isinstance(node, dict):

        if node.get("format") == "int-or-string":

            node.clear()

            node.update(
                INT_OR_STRING_SCHEMA
            )

            return node


        if (
            "properties" in node
            and "additionalProperties" not in node
            and (
                not is_root
                or DENY_ROOT_ADDITIONAL_PROPERTIES
            )
        ):

            node["additionalProperties"] = False


        for key, value in node.items():

            optimize_schema(
                value,
                False
            )


    elif isinstance(node, list):

        for item in node:

            optimize_schema(
                item,
                False
            )


    return node



def write_schema_file(schema, filename):

    optimize_schema(
        schema,
        True
    )


    filename = os.path.basename(
        filename
    )


    schema_json = json.dumps(
        schema,
        indent=2,
        ensure_ascii=False
    )


    with open(
        filename,
        "w",
        encoding="utf-8",
        buffering=1024 * 1024
    ) as f:

        f.write(schema_json)
        f.write("\n")


    if not QUIET:

        print(
            f"JSON schema written to {filename}"
        )



def construct_value(loader, node):

    if not isinstance(
        node,
        yaml.ScalarNode
    ):

        raise yaml.constructor.ConstructorError(
            "while constructing a value",
            node.start_mark,
            "expected scalar",
            node.start_mark
        )


    yield str(
        node.value
    )



def load_source(path):

    if path.startswith(
        "http"
    ):

        return urllib.request.urlopen(
            path
        )


    return open(
        path,
        "r",
        encoding="utf-8"
    )



def process_crd(crd):

    results = []


    if "spec" not in crd:

        return results


    spec = crd["spec"]


    versions = spec.get(
        "versions"
    )


    if versions:

        for version in versions:

            schema = None


            if (
                "schema" in version
                and
                "openAPIV3Schema"
                in version["schema"]
            ):

                schema = (
                    version["schema"]
                    ["openAPIV3Schema"]
                )


            elif (
                "validation" in version
                and
                "openAPIV3Schema"
                in version["validation"]
            ):

                schema = (
                    version["validation"]
                    ["openAPIV3Schema"]
                )


            if schema is not None:

                filename = (
                    FILENAME_FORMAT.format(
                        kind=spec["names"]["kind"],
                        group=spec["group"].split(".")[0],
                        fullgroup=spec["group"],
                        version=version["name"]
                    )
                    .lower()
                    + ".json"
                )


                results.append(
                    (
                        schema,
                        filename
                    )
                )


    else:

        schema = (
            spec
            .get("validation", {})
            .get("openAPIV3Schema")
        )


        if schema is not None:

            filename = (
                FILENAME_FORMAT.format(
                    kind=spec["names"]["kind"],
                    group=spec["group"].split(".")[0],
                    fullgroup=spec["group"],
                    version=spec.get("version")
                )
                .lower()
                + ".json"
            )


            results.append(
                (
                    schema,
                    filename
                )
            )


    return results



def main():

    if len(sys.argv) < 2:

        print(
            f"Usage: {sys.argv[0]} FILE"
        )

        return 1



    yaml.SafeLoader.add_constructor(
        "tag:yaml.org,2002:value",
        construct_value
    )



    for source in sys.argv[1:]:

        with load_source(source) as stream:

            documents = yaml.load_all(
                stream,
                Loader=yaml.SafeLoader
            )


            for document in documents:

                if not document:

                    continue


                crds = []


                if "items" in document:

                    crds.extend(
                        document["items"]
                    )


                if (
                    document.get("kind")
                    ==
                    "CustomResourceDefinition"
                ):

                    crds.append(
                        document
                    )


                for crd in crds:

                    for schema, filename in process_crd(crd):

                        write_schema_file(
                            schema,
                            filename
                        )


    return 0



if __name__ == "__main__":

    sys.exit(
        main()
    )
