"""MTC! main driver"""

import argparse
import logging

from itertools import batched
from pathlib import Path
from tempfile import NamedTemporaryFile

import requests

from pwiki.mquery import MQuery
from pwiki.ns import NS
from pwiki.wiki import Wiki
from rich.logging import RichHandler

log = logging.getLogger(__name__)


def _main() -> None:
    """Main driver, to be run if this script is invoked directly."""
    cli_parser = argparse.ArgumentParser(description="mtc CLI")
    cli_parser.add_argument('-u', type=str, default="FSock", metavar="username", help="the username to use")
    cli_parser.add_argument('-f', action='store_true', help="Force (ignore filter) file transfer(s)")
    cli_parser.add_argument('-d', action='store_true', help="Activate dry run/debug mode (does not transfer files)")
    cli_parser.add_argument('-a', type=str, metavar="api_endpoint", default="https://mtc-api.toolforge.org", help="The default desc generation API endpoint to use.  Defaults to public toolforge instance.")
    cli_parser.add_argument('titles', type=str, nargs='*', help='Files, usernames, templates, or categories')
    args = cli_parser.parse_args()

    if not args.titles:
        cli_parser.print_help()
        return

    handler = RichHandler(rich_tracebacks=True)
    for s in ("pwiki", "mtc"):
        lg = logging.getLogger(s)
        lg.addHandler(handler)
        lg.setLevel("DEBUG")

    l = set()
    wiki = Wiki()
    for s in args.titles:
        if wiki.in_ns(s, NS.FILE):
            l.add(s)
        elif wiki.in_ns(s, NS.CATEGORY):
            l.update(wiki.category_members(s, NS.FILE))
        elif wiki.in_ns(s, NS.TEMPLATE):
            l.update(wiki.what_transcludes_here(s, NS.FILE))
        else:
            l.update(wiki.user_uploads(s))

    if not l:
        return

    base_payload = {"force": True} if args.f else {}
    fails = []
    com = Wiki("commons.wikimedia.org", args.u)
    image_infos = MQuery.image_info(wiki, list(l))
    for b in batched(l, 25):
        r = requests.post(f"{args.a}/generate", json=base_payload | {"titles": b}).json()
        fails += r["fails"]
        for jo in r["generated_text"]:
            if args.d:
                print(f"{'-'*50}\n{jo}\n{'-'*50}")
                continue

            with NamedTemporaryFile(buffering=0) as f:
                f.write(requests.get(image_infos[enwp_title := jo["enwp_title"]][0].url, headers={"User-Agent": "mtc-cli"}).content)

                if not com.upload(Path(f.name), com.nss(jo["com_title"]), jo["desc"], f"Transferred from en.wikipedia"):
                    fails.append(enwp_title)
                    log.error("Failed to transfer '%s'", enwp_title)
                    continue

    if fails:
        log.warning("Failed with %d errors: %s", len(fails), fails)

    com.save_cookies()


if __name__ == "__main__":
    _main()
