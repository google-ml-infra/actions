def   my_macro(name, srcs = []):
    # This file has bad indentation and spacing
    native.genrule(
        name = name,
        srcs = [
            "z_last.txt",
            "a_first.txt",
        ],
        outs = [name + ".out"],
        cmd = "cat $(SRCS) > $@",
    )

def another_macro(name,srcs=[ ]):
    # This file has bad indentation and spacing
    native.genrule(
        name = name,
        srcs = [
            "z_last.txt",
            "a_first.txt",  # Not sorted
        ],
        outs = [name + ".out"],
        cmd = "cat $(SRCS) > $@",
    )
