"""Classes and methods supporting MTC!"""

import argparse
import logging
import re

from pathlib import Path
from random import randint
from tempfile import NamedTemporaryFile
from textwrap import dedent

import requests

from rich.logging import RichHandler

from pwiki.dwrap import ImageInfo
from pwiki.mquery import MQuery
from pwiki.ns import NS
from pwiki.wiki import Wiki
from pwiki.wgen import load_px
from pwiki.wparser import WParser, WikiTemplate

from fastilybot.core import FastilyBotBase, XQuery


log = logging.getLogger(__name__)

_VERSION = "1.1.2"
_MTC = "Wikipedia:MTC!"
_USER = "FSock"
_USER_AT_PROJECT = "{{{{User at project|{}|w|en}}}}"


class MTC(FastilyBotBase):

    def __init__(self, wiki: Wiki) -> None:
        super().__init__(wiki)

        # if not wiki.login(_USER, pw := load_px().get(_USER)): #or not self.com.login(_USER, pw):
        #     raise RuntimeError("Could not login, is your username and password right?")

        self.blacklist: set[str] = set(self.wiki.links_on_page(f"{_MTC}/Blacklist"))
        self.whitelist: set[str] = set(self.wiki.links_on_page(f"{_MTC}/Whitelist"))

    def generate_commons_title(self, titles: list[str]) -> dict:
        out = {s: s for s in titles}

        for s in XQuery.exists_filter(self.com, titles):
            base, ext = s.rsplit(".", 1)
            out[s] = result.pop() if (result := XQuery.exists_filter(self.com, [f"{base} {i}.{ext}" for i in range(1, 11)] + [f"{base} {randint(1000,1000000)}.{ext}"], False)) else None

        return out

    def fuzz_for_param(self, target_key: str, t: WikiTemplate, default: str = "") -> str:
        if not t:
            return default

        rgx = re.compile(r"(?i)" + re.sub(r"[ _]", "[ _]", target_key) + "")
        return str(next((t[k] for k in t if rgx.match(k)), default)).strip()

    def generate_text(self, title: str, is_own_work: bool, ii_l: list[ImageInfo]) -> str:
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
            # print("HERe")
            lic_section += f"\n{t}"
            t.drop()

        # fill out Information Template
        desc = dedent(f"""\
            == {{{{int:filedesc}}}} ==
            {{{{Information
            |description={self.fuzz_for_param("Description", info)}{str(doc_root).strip()}
            |date={self.fuzz_for_param("Date", info)}
            |source={self.fuzz_for_param("Source", info, '{{Own work by original uploader}}' if is_own_work else '')}
            |author={self.fuzz_for_param("Author", info, '[[User:{u}|{u}]]'.format(u=uploader) if is_own_work else '')}
            |permission={self.fuzz_for_param("Permission", info)}
            |other versions={self.fuzz_for_param("Other_versions", info)}
            }}}}\n\n""") + lic_section

        desc = re.sub(r"(?<=\[\[)(.+?\]\])", "w:\\1", desc)  # add enwp prefix to links
        desc = re.sub(r"(?i)\[\[(w::|w:w:)", "[[w:", desc)  # Remove any double colons in interwiki links
        desc = re.sub(r"\n{3,}", "\n", desc)  # Remove excessive spacing

        # Generate Upload Log Section
        desc += "\n\n== {{Original upload log}} ==\n" + f"{{{{Original file page|en.wikipedia|{self.wiki.nss(title)}}}}}" + "\n{| class=\"wikitable\"\n! {{int:filehist-datetime}} !! {{int:filehist-dimensions}} !! {{int:filehist-user}} !! {{int:filehist-comment}}"
        for ii in ii_l:
            ii.summary = ii.summary.replace('\n', ' ').replace('  ', ' ')
            desc += f"\n|-\n| {ii.timestamp:%Y-%m-%d %H:%M:%S} || {ii.height} × {ii.width} || [[w:User:{ii.user}|{ii.user}]] || ''<nowiki>{ii.summary}</nowiki>''"

        return desc + "\n|}\n\n{{Subst:Unc}}"

    def transfer(self, titles: list[str], force: bool = False, dry: bool = False, tag: bool = False) -> str:
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
                if not self.com.upload(Path(f.name), self.com.nss(com_title), desc, f"Transferred from en.wikipedia ([[w:{_MTC}|MTC!]]) ({_VERSION})"):
                    fails.append(title)
                    log.error("Failed to transfer '%s'", title)
                    continue

            if tag:
                self.wiki.edit(title, prepend=f"{{{{subst:ncd|{title}}}}}\n", summary=f"Transferred to Commons ([[{_MTC}|MTC!]]) ({_VERSION})")

        if fails:
            log.warning("Failed with %d errors: %s", len(fails), fails)


def _main() -> None:
    """Main driver, to be run if this script is invoked directly."""

    cli_parser = argparse.ArgumentParser(description="mtc CLI")
    cli_parser.add_argument('-f', action='store_true', help="Force (ignore filter) file transfer(s)")
    cli_parser.add_argument('-d', action='store_true', help="Activate dry run/debug mode (does not transfer files)")
    cli_parser.add_argument('-t', action='store_true', help="Add a Now Commons tag to the enwp file")
    cli_parser.add_argument('titles', type=str, nargs='*', help='Files, usernames, templates, or categories')
    args = cli_parser.parse_args()

    if not args.titles:
        cli_parser.print_help()
        return

    handler = RichHandler(rich_tracebacks=True)
    for s in ("pwiki", "fastilybot", "mtc"):
        lg = logging.getLogger(s)
        lg.addHandler(handler)
        lg.setLevel("DEBUG")

    l = set()
    wiki = Wiki(username=_USER, password=load_px().get(_USER))
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
