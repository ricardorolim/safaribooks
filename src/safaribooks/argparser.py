import argparse

def parse_args(orly_base_url: str) -> argparse.Namespace:
    arguments = argparse.ArgumentParser(
        prog="safaribooks.py",
        description="Download and generate an EPUB of your favorite books"
        " from Safari Books Online.",
        add_help=False,
        allow_abbrev=False,
    )

    login_arg_group = arguments.add_mutually_exclusive_group()
    login_arg_group.add_argument(
        "--cred",
        metavar="<EMAIL:PASS>",
        default=False,
        help="Credentials used to perform the auth login on Safari Books Online."
        ' Es. ` --cred "account_mail@mail.com:password01" `.',
    )
    login_arg_group.add_argument(
        "--login",
        action="store_true",
        help="Prompt for credentials used to perform the auth login on Safari Books Online.",
    )

    arguments.add_argument(
        "--no-cookies",
        dest="no_cookies",
        action="store_true",
        help="Prevent your session data to be saved into `cookies.json` file.",
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
        type=int,
        metavar="<BOOK ID>",
        help="Book digits ID that you want to download. You can find it in the URL (X-es):"
        f" `{orly_base_url}/library/view/book-name/XXXXXXXXXXXXX/`",
    )

    args_parsed = arguments.parse_args()
    if args_parsed.cred or args_parsed.login:
        print(
            "WARNING: Due to recent changes on ORLY website, \n"
            "the `--cred` and `--login` options are temporarily disabled.\n"
            "    Please use the `cookies.json` file to authenticate your account.\n"
            "    See: https://github.com/lorenzodifuccia/safaribooks/issues/358"
        )
        arguments.exit()

    else:
        if args_parsed.no_cookies:
            arguments.error(
                "invalid option: `--no-cookies` is valid only if you use the `--cred` option"
            )

    return args_parsed
