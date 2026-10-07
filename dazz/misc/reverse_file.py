import argparse

def reverse_file_content(source_filepath, destination_filepath):
    """Reads a file, reverses its lines, and writes to a new file."""
    try:
        with open(source_filepath, 'r') as infile:
            lines = infile.readlines()
        with open(destination_filepath, 'w') as outfile:
            # Use reversed() for an iterator, which can be more memory efficient for large files
            outfile.writelines(reversed(lines))
        print(f"Successfully reversed '{source_filepath}' to '{destination_filepath}'.")
    except FileNotFoundError:
        print(f"Error: The file '{source_filepath}' was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Reverses the lines of a text file and writes to a new file."
    )
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="The path to the input file whose lines will be reversed."
    )
    parser.add_argument(
        "-o", "--output",
        required=True,
        help="The path to the output file where the reversed content will be written."
    )

    args = parser.parse_args()

    reverse_file_content(args.input, args.output)