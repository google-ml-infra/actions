"""
This is a correctly formatted .bzl file for testing.
It defines a simple custom rule.
"""

load("@bazel_skylib//lib:attrs.bzl", "attrs")
load("@bazel_skylib//lib:collections.bzl", "dedup_list")
load("//some/dependency:defs.bzl", "dependency_macro")

def _my_custom_rule_impl(ctx):
    """Implementation for my_custom_rule."""
    input_file = ctx.files.src[0]
    output_file = ctx.actions.declare_file(ctx.attr.name + ".out")

    ctx.actions.run(
        inputs = [input_file],
        outputs = [output_file],
        executable = "/usr/bin/some_tool",
        arguments = [
            "--input",
            input_file.path,
            "--output",
            output_file.path,
            "--verbose",
        ],
        mnemonic = "MyCustomRule",
    )

    dependency_macro(
        name = ctx.attr.name + "_dep",
        data = ctx.attr.data,
    )

    return [DefaultInfo(files = depset([output_file]))]

my_custom_rule = rule(
    implementation = _my_custom_rule_impl,
    attrs = {
        "data": attrs.list(
            default = [],
            allow_files = True,
            doc = "Additional data files.",
        ),
        "src": attrs.label(
            allow_single_file = True,
            mandatory = True,
            doc = "The primary source file.",
        ),
    },
    doc = "A custom rule that processes a source file.",
)

def another_macro(name, value, some_list = []):
    """Another example macro."""
    print("Running another_macro with value: %s" % value)
    dedup_list(some_list)
