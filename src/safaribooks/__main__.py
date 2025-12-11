#!/usr/bin/env python3
# coding: utf-8
import sys

from safaribooks.downloader import Downloader
from safaribooks.argparser import parse_args


def main() -> None:
    args_parsed = parse_args()
    safari = Downloader(args_parsed, args_parsed.bookid, args_parsed.cred)
    safari.download()
    sys.exit(0)


if __name__ == "__main__":
    main()
