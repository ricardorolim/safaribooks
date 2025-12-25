import argparse

def parse_args(orly_base_url: str) -> argparse.Namespace:
    arguments = argparse.ArgumentParser(
        prog="safaribooks.py",
        description="Download and generate an EPUB of your favorite books"
        " from Safari Books Online.",
        add_help=False,
        allow_abbrev=False,
    )
    arguments.add_argument(
        "--no-cookies",
        dest="no_cookies",
        action="store_true",
        help="Removes your cookies file `cookies.json` at the end of execution.",
    )
    arguments.add_argument(
        "--kindle",
        dest="kindle",
        action="store_true",
        help="Add some CSS rules that block overflow on `table` and `pre` elements."
        " Use this option if you're going to export the EPUB to E-Readers like Amazon Kindle.",
    )
    arguments.add_argument(
        "--preserve-log",
        dest="log",
        action="store_true",
        help="Leave the `info_XXXXXXXXXXXXX.log` file even if there isn't any error.",
    )
    arguments.add_argument(
        "--help",
        action="help",
        default=argparse.SUPPRESS,
        help="Show this help message.",
    )
    arguments.add_argument(
        "bookid",
        type=str,
        metavar="<BOOK ID>",
        help="Book digits ID that you want to download. You can find it in the URL (X-es):"
        f" `{orly_base_url}/library/view/book-name/XXXXXXXXXXXXX/`",
    )
    return arguments.parse_args()
