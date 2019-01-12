import znc
import html
import re
import os
import os.path
import urllib.parse

# regexes taken from pygments, under a BSD 2-clause license
# https://bitbucket.org/birkenfeld/pygments-main/src/default/LICENSE
class Colorizer:
    timestamp = r"""
        (
          # irssi / xchat and others
          (?: \[|\()?                  # Opening bracket or paren for the timestamp
            (?:                        # Timestamp
                (?: (?:\d{1,4} [-/])*  # Date as - or /-separated groups of digits
                    (?:\d{1,4})
                 [T ])?                # Date/time separator: T or space
                (?: \d?\d [:.])*       # Time as :/.-separated groups of 1 or 2 digits
                    (?: \d?\d)
            )
          (?: \]|\))?\s+               # Closing bracket or paren for the timestamp
        )?
    """
    # (regex, [wholeclass, groupclasses, ...])
    matchersrc = [
        # log start/end
        (r'^\*\*\*\*(.*)\*\*\*\*$', ['muted', None]),
        # hack
        ('^' + timestamp + r'(\s*<([^>]*)>\s*)$', [None, 'timestamp', 'nickname-bracket', 'nickname']),
        # normal messages
        ('^' + timestamp + r"""
            (\s*<(.*?)>\s*)            # Nick-bracket and Nick
            (?: (\S+):(?!//))?         # Prefix
            .*$                        # rest of message
        """, [None, 'timestamp', 'nickname-bracket', 'nickname', 'prefix']),
        # /me messages
        ('^' + timestamp + r"""
            (\s*[*]\s+)                # Star
            (\S+\s+)                   # Nick
            .*$                        # rest of message
        """, [None, 'timestamp', 'keyword', 'nickname']),
        # join / part messages
        ('^' + timestamp + r"""
            (\s*(?:\*{3}|<?-[!@=P]?->?)\s*)  # Star(s) or symbols
            (.*)$                      # rest of message
        """, [None, 'timestamp', 'keyword', 'muted']),
        # catchall with timestamp
        ('^' + timestamp + '.*$', [None, 'timestamp']),
    ]

    matchers = []
    for resrc, groups in matchersrc:
        matchers.append((re.compile(resrc, re.X | re.M), groups))

    def colorize(self, line):
        for i, (r, groups) in enumerate(self.matchers):
            res = r.match(line)
            if not res:
                continue

            return [(cls, res.span(i)) for i, cls in enumerate(groups) if cls]
        return []

    def chunkify(self, line, spans):
        keyidx = set([0, len(line)])
        for _, (start, end) in spans:
            if start < 0 or end < 0:
                continue
            keyidx.add(start)
            keyidx.add(end)
        keyidx = list(sorted(keyidx))
        chunks = []
        for i in range(len(keyidx) - 1):
            start = keyidx[i]
            end = keyidx[i + 1]
            cls = []
            for testcls, (clsstart, clsend) in spans:
                if clsstart <= start and end <= clsend:
                    cls.append(testcls)
            chunks.append((cls, line[start:end]))

        return chunks

    def make_html(self, chunks, prefix='log-'):
        gather = ''
        for cls, chunk in chunks:
            if cls:
                gather += '<span class="{0}">{1}</span>'.format(' '.join([prefix + c for c in cls]), html.escape(chunk))
            else:
                gather += html.escape(chunk)
        return gather

class logviewer(znc.Module):
    module_types = [
        znc.CModInfo.GlobalModule,
        znc.CModInfo.UserModule,
        znc.CModInfo.NetworkModule,
    ]
    description = 'interface to view log files from ZNC web server'
    wiki_page = 'LogViewer'

    def OnLoad(self, args, message):
        return True

    def WebRequiresLogin(self):
        return True

    def WebRequiresAdmin(self):
        return self.GetType() == znc.CModInfo.GlobalModule

    def GetWebMenuTitle(self):
        return "Log Viewer"

    def OnWebPreRequest(self, sock, page):
        if page == 'raw':
            # only raw needs special handling. the normal code
            # can handle every other case
            if self.WebRequiresAdmin() and not self.GetUser().IsAdmin():
                return False
            self.render_raw(sock)
            sock.Close()
            return True
        return False

    def OnWebRequest(self, sock, page, tmpl):
        if page == 'index':
            return self.render_dir(sock, tmpl)
        elif page == 'log':
            return self.render_log(sock, tmpl)
        else:
            sock.PrintErrorPage(404, "Not Found", "unknown page")
            return False

    def render_dir(self, sock, tmpl):
        path, rel = self.get_safe_path(sock, dir=True)
        if not path:
            return False

        self.render_breadcrumbs(tmpl, rel, dir=True)

        for name in sorted(os.listdir(path)):
            subpath = os.path.join(path, name)
            subrel = os.path.join(rel, name)
            
            row = tmpl.AddRow('FileList')
            row['name'] = name
            if os.path.isfile(subpath):
                row['type'] = 'file'
                row['url'] = self.get_url('log', {'path': subrel})
                row['size'] = self.pretty_number(os.path.getsize(subpath), 'B', True)
            elif os.path.isdir(subpath):
                row['type'] = 'dir'
                row['url'] = self.get_url('index', {'path': subrel})
                row['size'] = self.pretty_number(len(os.listdir(subpath)))

        return True

    def render_log(self, sock, tmpl):
        path, rel = self.get_safe_path(sock)
        if not path:
            return False

        self.render_breadcrumbs(tmpl, rel)

        row = tmpl.AddRow('LogFormats')
        row['url'] = self.get_url('raw', {'path': rel})
        row['name'] = 'Raw Text'
        color = Colorizer()
        with open(path, encoding='utf-8', errors='replace') as f:
            for i, line in enumerate(f.readlines()):
                row = tmpl.AddRow('LogLines')
                line = line.strip()
                spans = color.colorize(line)
                chunks = color.chunkify(line, spans)
                timestamp = []
                nickname = []
                rest = []
                in_other = False
                # do nickname colors, and also partition into
                # timestamp, nickname, rest
                for cls, chunk in chunks:
                    if 'nickname' in cls or 'prefix' in cls:
                        namecolor = hash(chunk.strip()) % 10
                        cls.append('nickname-{0}'.format(namecolor))
                    if in_other:
                        rest.append((cls, chunk))
                    else:
                        if 'nickname-bracket' in cls or 'keyword' in cls or 'nickname' in cls:
                            nickname.append((cls, chunk))
                        elif 'timestamp' in cls:
                            timestamp.append((cls, chunk))
                        else:
                            in_other = True
                            rest.append((cls, chunk))
                row['timestamp'] = color.make_html(timestamp)
                row['nickname'] = color.make_html(nickname)
                row['message'] = color.make_html(rest)
                row['lineno'] = str(i + 1)

        return True

    def render_raw(self, sock):
        path, rel = self.get_safe_path(sock)
        if not path:
            return False
        sock.PrintFile(path, 'text/plain')
        return True

    def render_breadcrumbs(self, tmpl, rel, dir=False):
        parts = [p for p in os.path.split(rel) if p]
        sofar = ''
        row = tmpl.AddRow('Breadcrumbs')
        tmpl['breadcrumbs_root'] = './'
        for i, part in enumerate(parts):
            row = tmpl.AddRow('Breadcrumbs')
            sofar = os.path.join(sofar, part)
            row['url'] = self.get_url('index', {'path': sofar})
            row['name'] = part
            row['type'] = 'dir' if (dir or i < len(parts) - 1) else 'file'
            row['last'] = 'true' if (i == len(parts) - 1) else 'false'

    def get_url(self, name, args={}):
        if name == 'index':
            name = ''
        if args:
            name += '?' + urllib.parse.urlencode(args)
        return name

    def pretty_number(self, n, unit='', log2=False):
        prefixes = ['', 'k', 'M', 'G', 'T', 'P', 'E', 'Z', 'Y']
        base = 1000
        if log2:
            base = 1024
        for prefix in prefixes:
            if n < 9999:
                break
            n = n / base
        s = '{0}'.format(int(round(n)))
        suffix = prefix + ('i' if (log2 and prefix) else '') + unit
        if suffix:
            s += ' ' + suffix
        return s

    def get_safe_path(self, sock, dir=False):
        path = sock.GetParam('path', False)
        base = os.path.abspath(self.get_log_dir(sock))
        fullpath = os.path.abspath(os.path.join(base, path))
        if not fullpath.startswith(base):
            sock.PrintErrorPage(404, "Not Found", "bad path")
            return None, None
        if dir and not os.path.isdir(fullpath):
            sock.PrintErrorPage(404, "Not Found", "not a directory")
            return None, None
        if not dir and not os.path.isfile(fullpath):
            sock.PrintErrorPage(404, "Not Found", "not a file")
            return None, None
        rel = os.path.relpath(fullpath, base)
        if rel == '.':
            rel = ''
        return fullpath, rel

    def get_log_dir(self, sock):
        base = znc.CZNC.Get().GetZNCPath()
        ty = self.GetType()
        user = sock.GetUser()
        if ty == znc.CModInfo.GlobalModule:
            return os.path.join(base, 'moddata', 'log', user)
        elif ty == znc.CModInfo.UserModule:
            return os.path.join(base, 'users', user, 'moddata', 'log')
        elif ty == znc.CModInfo.NetworkModule:
            network = self.GetNetwork().GetName()
            return os.path.join(base, 'users', user, 'networks', network, 'moddata', 'log')
        else:
            raise RuntimeError('unknown plugin type')
