# mtc-cli
[![Python 3.9+](https://upload.wikimedia.org/wikipedia/commons/4/4f/Blue_Python_3.9%2B_Shield_Badge.svg)](https://www.python.org)
[![MediaWiki 1.35+](https://upload.wikimedia.org/wikipedia/commons/b/b3/Blue_MediaWiki_1.35%2B_Shield_Badge.svg)](https://www.mediawiki.org/wiki/MediaWiki)
[![License: GPL v3](https://upload.wikimedia.org/wikipedia/commons/8/86/GPL_v3_Blue_Badge.svg)](https://www.gnu.org/licenses/gpl-3.0.en.html)

mtc-cli is a command line tool that helps simplify and automate file imports from Wikipedia to Commons.

This is the rewritten, spiritual successor to the original [MTC!](https://github.com/fastily/mtc) tool.

### Install
```bash
pip install mtc-cli
```

### Usage
```
usage: __main__.py [-h] [-u username] [-f] [-d] [-t] [titles ...]

mtc CLI

positional arguments:
  titles       Files, usernames, templates, or categories

options:
  -h, --help   show this help message and exit
  -u username  the username to use
  -f           Force (ignore filter) file transfer(s)
  -d           Activate dry run/debug mode (does not transfer files)
  -t           Add a Now Commons tag to the enwp file
```

👉 Password is set via env variable `<USERNAME>_PW`, such that `<USERNAME>` is the username of the bot in all caps.