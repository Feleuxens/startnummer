import argparse

from startnummer.adapters.entrylist.ergebnisse_leichtathletik_de import LeichtathletikDeEntryListParser


def main() -> SystemExit | None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--entry-list",
        help="entry table source: saved Competitoroverview HTML file, raw HTML, or URL",
    )
    args = parser.parse_args()

    if not args.entry_list:
        print("entry table source: not specified")
        return SystemExit(1)

    entry_list = LeichtathletikDeEntryListParser().parse(args.entry_list)
    #print(entry_list)
    return None


if __name__ == "__main__":
    main()
