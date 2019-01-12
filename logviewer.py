import znc
import os
import os.path
import urllib.parse

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
        with open(path, encoding='utf-8', errors='replace') as f:
            for i, line in enumerate(f.readlines()):
                row = tmpl.AddRow('LogLines')
                row['line'] = line
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
