#!/bin/bash -e

book_id=$1

if [[ -z "$book_id" ]]; then
    echo "Error: No book ID provided"
    echo "Usage: $0 <book_id>"
    exit 1
fi

uv run --with browser_cookie3 python retrieve_cookies.py
uv run safaribooks $book_id

epub_path=$(find Books -name ${book_id}.epub -exec dirname {} \;)
epub_file="$epub_path/${book_id}.epub"
epub_cleared="$epub_path/${book_id}_clear.epub"

ebook-convert "$epub_file" "$epub_cleared"
mv "$epub_cleared" "$epub_file"

echo Output renamed to: "$epub_file"
