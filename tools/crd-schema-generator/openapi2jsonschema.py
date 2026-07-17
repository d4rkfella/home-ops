#!/usr/bin/env python3

import yaml
import json
import sys
import os
import urllib.request


if "DISABLE_SSL_CERT_VALIDATION" in os.environ:
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context


def additional_properties(data, skip=False):

    if isinstance(data, dict):

        if "properties" in data and not skip:
            if "additionalProperties" not in data:
                data["additionalProperties"] = False

        for value in data.values():
            additional_properties(value)

    return data



def replace_int_or_string(data):

    if isinstance(data, dict):

        new = {}

        for key, value in data.items():

            if isinstance(value, dict):

                if value.get("format") == "int-or-string":

                    new[key] = {
                        "oneOf": [
                            {
                                "type": "string"
                            },
                            {
                                "type": "integer"
                            }
                        ]
                    }

                else:
                    new[key] = replace_int_or_string(value)

            elif isinstance(value, list):

                new[key] = [
                    replace_int_or_string(item)
                    for item in value
                ]

            else:
                new[key] = value

        return new

    return data



def write_schema_file(schema, filename):

    schema = additional_properties(
        schema,
        skip=not os.getenv(
            "DENY_ROOT_ADDITIONAL_PROPERTIES"
        )
    )

    schema = replace_int_or_string(schema)


    schema_json = json.dumps(
        schema,
        indent=2,
        ensure_ascii=False
    )


    filename = os.path.basename(filename)


    with open(
        filename,
        "w",
        encoding="utf-8"
    ) as f:

        f.write(schema_json)


    print(
        f"JSON schema written to {filename}"
    )



def construct_value(loader, node):

    if not isinstance(node, yaml.ScalarNode):

        raise yaml.constructor.ConstructorError(
            "while constructing a value",
            node.start_mark,
            "expected scalar",
            node.start_mark
        )

    yield str(node.value)



if __name__ == "__main__":


    if len(sys.argv) < 2:

        print(
            f"Missing FILE parameter.\nUsage: {sys.argv[0]} [FILE]"
        )

        sys.exit(1)



    for crd_file in sys.argv[1:]:


        if crd_file.startswith("http"):

            f = urllib.request.urlopen(crd_file)

        else:

            f = open(crd_file)



        with f:


            defs = []


            yaml.SafeLoader.add_constructor(
                "tag:yaml.org,2002:value",
                construct_value
            )



            for document in yaml.load_all(
                f,
                Loader=yaml.SafeLoader
            ):


                if document is None:
                    continue


                if "items" in document:
                    defs.extend(document["items"])


                if document.get("kind") == "CustomResourceDefinition":

                    defs.append(document)



            for crd in defs:


                filename_format = os.getenv(
                    "FILENAME_FORMAT",
                    "{kind}_{version}"
                )



                if (
                    "spec" in crd
                    and "versions" in crd["spec"]
                    and crd["spec"]["versions"]
                ):


                    for version in crd["spec"]["versions"]:


                        schema = None


                        if (
                            "schema" in version
                            and "openAPIV3Schema"
                            in version["schema"]
                        ):

                            schema = (
                                version["schema"]["openAPIV3Schema"]
                            )


                        elif (
                            "validation" in crd["spec"]
                            and "openAPIV3Schema"
                            in crd["spec"]["validation"]
                        ):

                            schema = (
                                crd["spec"]["validation"]["openAPIV3Schema"]
                            )



                        if schema is not None:


                            filename = (
                                filename_format.format(
                                    kind=crd["spec"]["names"]["kind"],
                                    group=crd["spec"]["group"].split(".")[0],
                                    fullgroup=crd["spec"]["group"],
                                    version=version["name"],
                                ).lower()
                                + ".json"
                            )


                            write_schema_file(
                                schema,
                                filename
                            )



                elif (
                    "spec" in crd
                    and "validation" in crd["spec"]
                    and "openAPIV3Schema"
                    in crd["spec"]["validation"]
                ):


                    filename = (
                        filename_format.format(
                            kind=crd["spec"]["names"]["kind"],
                            group=crd["spec"]["group"].split(".")[0],
                            fullgroup=crd["spec"]["group"],
                            version=crd["spec"]["version"],
                        ).lower()
                        + ".json"
                    )


                    write_schema_file(
                        crd["spec"]["validation"]["openAPIV3Schema"],
                        filename
                    )


    sys.exit(0)
