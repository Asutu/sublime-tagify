import sublime
import sublime_plugin
import os
import re


TAG_RE = '((?:[\._a-zA-Z0-9]+))'


def natsort(s, _nsre=re.compile('([0-9]+)')):
    # https://stackoverflow.com/a/16090640/1738879
    return [int(text) if text.isdigit() else text.lower() for text in _nsre.split(s)]


class Prefs:
    @staticmethod
    def read():
        settings = sublime.load_settings('Tagify.sublime-settings')
        Prefs.common_tags = settings.get('common_tags', [])
        Prefs.blacklisted_tags = set(settings.get('blacklisted_tags', ["property"]) or [])
        Prefs.analyse_on_start = settings.get('analyse_on_start', True)
        Prefs.extensions = settings.get('extensions', ["md", "py", "html", "htm", "js"])
        Prefs.tag_anchor = settings.get('tag_anchor', "#@")

    @staticmethod
    def load():
        settings = sublime.load_settings('Tagify.sublime-settings')
        settings.add_on_change('common_tags', Prefs.read)
        settings.add_on_change('blacklisted_tags', Prefs.read)
        settings.add_on_change('analyse_on_start', Prefs.read)
        settings.add_on_change('extensions', Prefs.read)
        settings.add_on_change('tag_anchor', Prefs.read)
        Prefs.read()


class TagifyCommon:
    data = {}
    taglist = []
    ready = False


class Tagifier(sublime_plugin.EventListener):

    def __init__(self, *args, **kw):
        super(Tagifier, self).__init__(*args, **kw)
        Prefs.load()
        self.last_sel = None
        self.tag_find = '{0}{1}'.format(Prefs.tag_anchor, TAG_RE)

    def analyse_regions(self, view, regions):
        for region in regions:
            region = view.line(region)
            tag_region = view.find(self.tag_find, region.a)
            if tag_region.a >= 0:
                self.tags_regions.append(tag_region)
        view.add_regions("tagify", self.tags_regions, "markup.inserted",
                         "bookmark", sublime.HIDDEN)

    def reanalyse_all(self, view):
        self.tags_regions = []
        regions = view.find_all(self.tag_find)
        self.analyse_regions(view, regions)

    def on_post_save_async(self, view):
        self.reanalyse_all(view)

    def on_load_async(self, view):
        self.reanalyse_all(view)

    def on_selection_modified(self, view):
        sel = list(view.sel())
        if len(sel) != 1:
            return
        sel = sel[0]
        if self.last_sel == sel:
            return
        self.last_sel = sel
        for region in view.get_regions('tagify-link'):
            if region.contains(sel) and sel.size() > 0:
                name = view.substr(region)
                if name in TagifyCommon.data:
                    real_name = TagifyCommon.data[name]["file"]
                    line_no = TagifyCommon.data[name]["line"]
                    view.window().open_file(
                        "%s:%i" % (real_name, line_no), sublime.ENCODED_POSITION)
                    view.sel().clear()
                    return


class ShowTagsMenuCommand(sublime_plugin.TextCommand):
    def run(self, edit):

        tags = sorted(list(set(TagifyCommon.taglist + Prefs.common_tags)), key=natsort)

        def selected(pos):
            if pos >= 0:
                sel = self.view.sel()
                for region in sel:
                    self.view.run_command(
                        "insert", {'characters': Prefs.tag_anchor + tags[pos] + ' '})

        self.view.show_popup_menu(tags, selected)


class GenerateSummaryCommand(sublime_plugin.TextCommand):
    def run(self, edit, data):
        out = []
        cpos = 0
        regions = []
        for tag in sorted(data.keys(), key=natsort):
            # out.append("- %s - " % tag)
            tag_out = tag + '\n' + '=' * len(tag)
            out.append(tag_out)
            cpos += len(out[-1]) + 1
            for entry in data[tag]:
                opos = cpos
                out.append("%s  " % entry["short_file"])
                cpos += len(out[-1]) + 1
                TagifyCommon.data[entry["short_file"]] = entry
                # regions.append(sublime.Region(opos, cpos - 1))
                # need -3 because of the extra spaces at the end of line (for MD compatibility)
                regions.append(sublime.Region(opos, cpos - 3))
            out.append("")
            cpos += 1

        self.view.insert(edit, 0, "\n".join(out))
        # self.view.add_regions("tagify-link", regions, 'link', "", sublime.HIDDEN)
        self.view.add_regions("tagify-link", regions, 'link', "")
        self.view.set_read_only(True)
        self.view.set_scratch(True)


class TagifyCommand(sublime_plugin.WindowCommand):

    def __init__(self, arg):
        super(TagifyCommand, self).__init__(arg)
        Prefs.load()
        if Prefs.analyse_on_start and not TagifyCommon.ready:
            TagifyCommon.ready = True
            try:
                sublime.set_timeout_async(lambda: self.run(True), 0)
            except AttributeError:
                sublime.set_timeout(lambda: self.run(True), 0)

    def tagify_file(self, dirname, filename, ctags, folder_prefix):
        try:
            filelines = open(os.path.join(dirname, filename), errors='replace')
            do_encode = False
        except TypeError:
            filelines = open(os.path.join(dirname, filename))
            do_encode = True
        cpos = 0
        for n, line in enumerate(filelines):
            if do_encode:
                line = line.decode('utf-8', 'replace')

            for match in self.tag_re.finditer(line):
                tag_name = match.group(1)
                if tag_name in Prefs.blacklisted_tags:
                    continue
                path = os.path.join(dirname, filename)
                data = {
                    'region': (cpos + match.start(1), cpos + match.end(1)),
                    'file': path,
                    'short_file': "%s:%i" % (path[len(folder_prefix) + 1:], n + 1),
                    'line': n + 1
                }
                if tag_name in ctags:
                    ctags[tag_name].append(data)
                else:
                    ctags[tag_name] = [data]
            cpos += len(line)

    def process_file_list(self, paths, ctags, dir_prefix=None, root_prefix=None):
        for path in paths:
            if dir_prefix:
                dirname = dir_prefix
                filename = path
            else:
                dirname, filename = os.path.split(path)
            if root_prefix:
                folder = root_prefix
            else:
                folder = dirname
            split_filename = filename.split('.')
            ext = split_filename[-1]
            processed_extensions = Prefs.extensions
            if ext in processed_extensions:
                self.tagify_file(dirname, filename, ctags, folder)
            if None in processed_extensions and len(split_filename) == 1:
                self.tagify_file(dirname, filename, ctags, folder)

    def run(self, quiet=False):
        Prefs.read()
        # self.tag_re = re.compile("%s(.*?)$" % Prefs.tag_re)
        # self.tag_re = re.compile('{0}{1}(.*?)$'.format(Prefs.tag_anchor, TAG_RE))
        self.tag_re = re.compile('{0}{1}'.format(Prefs.tag_anchor, TAG_RE))

        ctags = {}

        # process opened folders
        folders = self.window.folders()
        for folder in folders:
            for dirname, dirnames, filenames in os.walk(folder):
                self.process_file_list(filenames, ctags, dirname, folder)

        # process opened files
        self.process_file_list([view.file_name() for view in self.window.views() if view.file_name()], ctags)

        # make all found occurrences unique across opened files/folders,
        # fix for https://github.com/taigh/sublime-tagify/issues/5
        unique_ctags = {}
        for tag, regions in ctags.items():
            unique_regions = []
            unique_path_lineno = set()
            for region in regions:
                path_lineno = (region['file'], region['line'])
                if path_lineno not in unique_path_lineno:
                    unique_path_lineno.add(path_lineno)
                    unique_regions.append(region)
                unique_ctags[tag] = unique_regions

        TagifyCommon.taglist = list(unique_ctags.keys())
        if not quiet:
            summary = self.window.new_file()
            summary.set_name("Tags summary")
            summary.run_command("generate_summary", {"data": unique_ctags})
