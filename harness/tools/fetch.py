#!/usr/bin/env python3
"""Simple script to fetch a URL's text content."""
import sys
import urllib.request


def fetch(url: str) -> str:
    """Fetch and return the text content of a URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.read().decode("utf-8", errors="ignore")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python fetch.py <url>")
        sys.exit(1)
    url = sys.argv[1]
    print(fetch(url))