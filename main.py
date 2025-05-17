import flatten
import argparse
import pathlib
import os
import shutil
import sys

from rich import print

sys.setrecursionlimit(3000)


def argparser():
    parser = argparse.ArgumentParser()
    parser.add_argument("dir", type=str, help="The working directory.")
    parser.add_argument(
        "-f",
        "--filelist",
        type=str,
        default="filelist.f",
        help="The file with list of design. Wont be used if -l is provided.",
    )
    parser.add_argument(
        "-l",
        "--list",
        help="The list of files to be flattened separated by `,`. If not provided, all files in the filelist will be used.",
        type=str,
        default="",
    )
    parser.add_argument("-t", "--top", type=str, default="top", help="The name of the top module.")
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="flatten.v",
        help="The output file containint the flattened module. Default = flatten.v",
    )
    parser.add_argument("-ex", "--exclude", type=str, default="", help="The filelist of excluded files.")
    parser.add_argument("-g", "--debug", default=False, action="store_true", help="Enable debug mode.")
    return parser


def main():
    print("[blue] Welcome to FlattenRTL! [/blue]")
    parser = argparser()
    args = parser.parse_args()

    directory = args.dir

    if args.list == "":
        input_filelist = pathlib.Path(directory, args.filelist)

        with open(input_filelist, "r") as f:
            files = f.readlines()
    else:
        input_filelist = args.list.split(",")
        files = []
        for item in input_filelist:
            files.append(item.strip())

    output_file = pathlib.Path(directory, args.output)

    if os.path.exists(output_file):
        os.remove(path=output_file)

    design = ""
    for item in files:
        item = item.strip()
        if item == "" or item.startswith("#"):
            continue

        with open(pathlib.Path(directory, item), "r") as f:
            content = f.read()
            design += content + "\n"

    if design.strip() == "":
        print("[red]ERROR[/red] The design is empty. Please check the filelist and the files.")
        print("[red]ERROR[/red] Exiting...")
        exit(1)

    exclude_module = set()
    if args.exclude != "":
        exclude_arr = args.exclude.split(",")
        for item in exclude_arr:
            exclude_module.add(item.strip())

    # all intermediate flattened results will be stored in directory/tmp
    if args.debug:
        tmp_folder = pathlib.Path(directory, "tmp")
        print(f"[green]INFO[/green] Intermediate flattened files will be saved in {tmp_folder}")

        if os.path.exists(tmp_folder):
            print(f"[green]INFO[/green] Removing existing files in {tmp_folder}")
            shutil.rmtree(tmp_folder)
        os.mkdir(tmp_folder)

    # flatten the preprocessed output file iteratively
    if design != "":
        tmp_idx = 0
        tmp_flatten_design = design
        done = False
        while not done:
            if args.debug:
                tmp_output_file = pathlib.Path(tmp_folder, f"flatten_{tmp_idx}.v")
                print(f"[green]INFO[/green] Writing intermediate flattened design in '{tmp_output_file}'")
                with open(tmp_output_file, "w") as f:
                    f.write(tmp_flatten_design)
                tmp_idx += 1  # tmp_idx加1
            done, tmp_flatten_design = flatten.pyflattenverilog(tmp_flatten_design, args.top, exclude_module)

        # write to output file
        with open(output_file, "w") as f:
            print(f"[green]INFO[/green] Writing the final flattened design into '{output_file}'")
            f.write(tmp_flatten_design)

        # format
        # print(f"[green]INFO[/green] Formating the flattened design in '{output_file}' using iStyle")


if __name__ == "__main__":
    # Calculate total duration
    import time

    start = time.time()
    main()
    end = time.time()
    print(f"[green]INFO[/green] Total time: {end - start} seconds")
