"""MTC! main driver and associated classes/methods"""

import argparse
import logging
import re

from pathlib import Path
from random import randint
from tempfile import NamedTemporaryFile

import requests

from rich.logging import RichHandler

from pwiki.dwrap import ImageInfo
from pwiki.mquery import MQuery
from pwiki.ns import NS
from pwiki.wiki import Wiki
from pwiki.wgen import load_px, setup_px
from pwiki.wparser import WParser, WikiTemplate

from fastilybot.core import FastilyBotBase, XQuery


log = logging.getLogger(__name__)

_MTC = "Wikipedia:MTC!"
_USER_AT_PROJECT = "{{{{User at project|{}|w|en}}}}"


class MTC(FastilyBotBase):
    """Methods for generating wikitext and performing transfers"""

    def __init__(self, wiki: Wiki) -> None:
        """Initializer, creates a new MTC instance.

        Args:
            wiki (Wiki): The Wiki object to use, this should already be logged-in.
        """
        super().__init__(wiki, auto_login=True)

        self.blacklist: set[str] = set(self.wiki.links_on_page(f"{_MTC}/Blacklist"))
        self.whitelist: set[str] = set(self.wiki.links_on_page(f"{_MTC}/Whitelist"))

    def generate_commons_title(self, titles: list[str]) -> dict:
        """Generates a title for a file on enwp in preparation for transfer to Commons.  If the name of the enwp file is not on Commons, then try various permutations of the title.

        Args:
            titles (list[str]): The enwp titles to generate Commons titles for 

        Returns:
            dict: A dict such that each key is the local file name and the value is the generated title for Commons.
        """
        out = {s: s for s in titles}

        for s in XQuery.exists_filter(self.com, titles):
            base, ext = s.rsplit(".", 1)
            out[s] = result.pop() if (result := XQuery.exists_filter(self.com, [f"{base} {i}.{ext}" for i in range(1, 11)] + [f"{base} {randint(1000,1000000)}.{ext}"], False)) else None

        return out

    def fuzz_for_param(self, target_key: str, t: WikiTemplate, default: str = "") -> str:
        """Fuzzy match template parameters to a given `target_key` and return the result.

        Args:
            target_key (str): The target key to fetch.  Will try ignore-case & underscore/space permutations
            t (WikiTemplate): The WikiTemplate to check
            default (str, optional): The default return value if nothing matching `target_key` was found. Defaults to "".

        Returns:
            str: The value associated with `target_key`, or the empty `str` if no match was found.
        """
        if not t:
            return default

        rgx = re.compile(r"(?i)" + re.sub(r"[ _]", "[ _]", target_key) + "")
        return str(next((t[k] for k in t if rgx.match(k)), default)).strip()

    def generate_text(self, title: str, is_own_work: bool, ii_l: list[ImageInfo]) -> str:
        """Generates Commons wikitext for the specified enwp file

        Args:
            title (str): The enwp title to make Commons wikitext for
            is_own_work (bool): Set `True` if this file is own work
            ii_l (list[ImageInfo]): The `ImageInfo` associated with `title`.

        Returns:
            str: The Commons wikitext generated for `title`.
        """
        if not (ii_l):
            log.error(f"No image info found for '{title}', please verify this exists on wiki.")
            return

        uploader = ii_l[-1].user

        # strip comments, categories, and wikitables (usually captions)
        txt = self.wiki.page_text(title)
        for rgx in [r"(?s)<!--.*?-->", r"(?i)\n?\[\[Category:.+?\]\]", r"\n?==.*?==\n?", r'(?si)\{\|\s*?class\s*?=\s*?"wikitable.+?\|\}']:
            txt = re.sub(rgx, "", txt)

        # parse down text
        doc_root = WParser.parse(self.wiki, title, txt)

        # drop templates we should not transfer (these exist on Commons)
        bl = {"Bots", "Copy to Wikimedia Commons"}
        for t in WikiTemplate.normalize(self.wiki, *doc_root.all_templates(), bypass_redirects=True):
            if t.title in bl:
                t.drop()

        # drop templates which do not exist on Commons
        tl = doc_root.all_templates()
        drop_list = XQuery.exists_filter(self.com, [(self.wiki.convert_ns(t.title, NS.TEMPLATE) if self.wiki.in_ns(t.title, NS.MAIN) else t.title) for t in tl], False)
        for t in tl:
            if (self.wiki.convert_ns(t.title, NS.TEMPLATE) if self.wiki.in_ns(t.title, NS.MAIN) else t.title) in drop_list:  # this is an uber dirty hack
                t.drop()

        # transform special templates
        info = None
        for t in doc_root.all_templates():
            if t.title == "Information":
                info = t
            elif t.title == "Self":
                if "author" not in t:
                    t["author"] = _USER_AT_PROJECT.format(uploader)
            elif t.title == "GFDL-self":
                t.title = "GFDL-self-en"
                t["author"] = _USER_AT_PROJECT.format(uploader)
            elif t.title == "PD-self":
                t.title = "PD-user-en"
                t["1"] = uploader
            elif t.title == "GFDL-self-with-disclaimers":
                t.title = "GFDL-user-en-with-disclaimers"
                t["1"] = uploader

        if info:
            info.drop()

        # Add any Commons-compatible top-level templates to License section.
        lic_section = "== {{int:filedesc}} =="
        for t in doc_root.all_templates():
            lic_section += f"\n{t}"
            t.drop()

        # fill out Information Template.  Don't use dedent, breaks on interpolated newlines
        desc = "== {{int:filedesc}} ==\n{{Information\n" + \
            f'|description={self.fuzz_for_param("Description", info)}{str(doc_root).strip()}\n' + \
            f'|date={self.fuzz_for_param("Date", info)}\n' + \
            f'|source={self.fuzz_for_param("Source", info, "{{Own work by original uploader}}" if is_own_work else "")}\n' + \
            f'|author={self.fuzz_for_param("Author", info, "[[User:{u}|{u}]]".format(u=uploader) if is_own_work else "")}\n' + \
            f'|permission={self.fuzz_for_param("Permission", info)}\n' + \
            f'|other versions={self.fuzz_for_param("Other_versions", info)}\n' + \
            "}}\n\n" + lic_section

        desc = re.sub(r"(?<=\[\[)(.+?\]\])", "w:\\1", desc)  # add enwp prefix to links
        desc = re.sub(r"(?i)\[\[w::", "[[w:", desc)  # Remove any double colons in interwiki links
        desc = re.sub(r"(?i)\[\[w:w:", "[[w:", desc)  # Remove duplicate interwiki prefixes
        desc = re.sub(r"\n{3,}", "\n", desc)  # Remove excessive spacing

        # Generate Upload Log Section
        desc += "\n\n== {{Original upload log}} ==\n" + f"{{{{Original file page|en.wikipedia|{self.wiki.nss(title)}}}}}" + "\n{| class=\"wikitable\"\n! {{int:filehist-datetime}} !! {{int:filehist-dimensions}} !! {{int:filehist-user}} !! {{int:filehist-comment}}"
        for ii in ii_l:
            ii.summary = ii.summary.replace('\n', ' ').replace('  ', ' ')
            desc += f"\n|-\n| {ii.timestamp:%Y-%m-%d %H:%M:%S} || {ii.height} × {ii.width} || [[w:User:{ii.user}|{ii.user}]] || ''<nowiki>{ii.summary}</nowiki>''"

        return desc + "\n|}\n\n{{Subst:Unc}}"

    def transfer(self, titles: list[str], force: bool = False, dry: bool = False, tag: bool = False):
        """Transfer a list of files

        Args:
            titles (list[str]): The titles to transfer
            force (bool, optional): Set `True` to disable the whitelist/blacklist sanity check. Defaults to False.
            dry (bool, optional): Set `True` to only print the generated wikitext to the terminal. Does not perform an actual transfer. Defaults to False.
            tag (bool, optional): Set `True` to tag the enwp file for deleteion after a successful transfer. Defaults to False.
        """
        if not titles:
            return

        cat_map = MQuery.categories_on_page(self.wiki, titles)
        if not force:
            titles = [title for title, cats in cat_map.items() if self.blacklist.isdisjoint(cats) and not self.whitelist.isdisjoint(cats)]  # filter blacklist & whitelist
            titles = [title for title, dupes in MQuery.duplicate_files(self.wiki, titles, False, True).items() if not dupes]  # don't transfer if already transferred

        title_map = self.generate_commons_title(titles)
        image_infos = MQuery.image_info(self.wiki, titles)
        fails = []
        for title in titles:
            if not (desc := self.generate_text(title, "Category:Self-published work" in cat_map[title], image_infos[title])) or not (com_title := title_map[title]):
                log.error("Could not generate title or wikitext for '%s', skipipng...", title)
                continue
            if dry:
                print(f"{'-'*50}\n{desc}\n{'-'*50}")
                continue

            with NamedTemporaryFile(buffering=0) as f:
                f.write(requests.get(image_infos[title][0].url).content)
                if not self.com.upload(Path(f.name), self.com.nss(com_title), desc, f"Transferred from en.wikipedia"):
                    fails.append(title)
                    log.error("Failed to transfer '%s'", title)
                    continue

            if tag:
                self.wiki.edit(title, prepend=f"{{{{subst:ncd|{title}}}}}\n", summary=f"Transferred to Commons")

        if fails:
            log.warning("Failed with %d errors: %s", len(fails), fails)


def _main() -> None:
    """Main driver, to be run if this script is invoked directly."""

    cli_parser = argparse.ArgumentParser(description="mtc CLI")
    cli_parser.add_argument('-u', type=str, default="FSock", metavar="username", help="the username to use")
    cli_parser.add_argument('-f', action='store_true', help="Force (ignore filter) file transfer(s)")
    cli_parser.add_argument('-d', action='store_true', help="Activate dry run/debug mode (does not transfer files)")
    cli_parser.add_argument('-t', action='store_true', help="Add a Now Commons tag to the enwp file")
    cli_parser.add_argument("--wgen", action='store_true', help="run wgen password manager")
    cli_parser.add_argument('titles', type=str, nargs='*', help='Files, usernames, templates, or categories')
    args = cli_parser.parse_args()

    if args.wgen:
        setup_px()
        return

    if not args.titles:
        cli_parser.print_help()
        return

    handler = RichHandler(rich_tracebacks=True)
    for s in ("pwiki", "fastilybot", "mtc"):
        lg = logging.getLogger(s)
        lg.addHandler(handler)
        lg.setLevel("DEBUG")

    l = set()
    wiki = Wiki(username=args.u, password=load_px().get(args.u))
    for s in args.titles:
        if wiki.in_ns(s, NS.FILE):
            l.add(s)
        elif wiki.in_ns(s, NS.CATEGORY):
            l.update(wiki.category_members(s, NS.FILE))
        elif wiki.in_ns(s, NS.TEMPLATE):
            l.update(wiki.what_transcludes_here(s, NS.FILE))
        else:
            l.update(wiki.user_uploads(s))

    (m := MTC(wiki)).transfer(list(l), args.f, args.d, args.t)
    m.wiki.save_cookies()
    m.com.save_cookies()


if __name__ == "__main__":
    _main()
