"""The corpus of the RAG: what the assistant may read before it answers.

Sources, each a folder on the machine that builds the index (never the
service itself — it runs without the source trees):

- fespp_on_trame: doc/wiki, doc/wiki-fr, doc/EN, doc/FR, doc/dev (and its
  widgets), the top-level Markdown files, the READMEs of the widgets, and
  every docstring of the Python package (module, class, function — with
  the qualified name);
- fesapi: the C++ headers, whose Doxygen blocks describe every RESQML /
  WITSML / PRODML class and method — the richest description of RESQML
  on disk; fespp: the same for the plugin, plus its proxies and class
  summaries (fespp_ia.fespp_docs);
- ParaView: the docstrings of paraview.simple, extracted in the app image
  (ia/corpus_cache/paraview_simple.jsonl, see the extraction script);
- the assistant's catalogue (--catalogue): one chunk per command;
- ia/corpus, every subfolder: anything the reader drops there -- .md,
  .txt, .pdf, .xsd (one chunk per documented type), .avsc (one chunk per
  ETP message) and .zip (an official Energistics package, read inside);
  ia/corpus/energistics is filled by fespp_ia.energistics_docs (the public
  Energistics documentation).

The developer's corpus (--developer) reads all of the above and, for who
writes code with fesapi and fetpapi rather than looks at a reservoir:
their SWIG interface files (the directives: what is renamed, instantiated,
converted, for which target language), their C++ and Python examples
function by function, their READMEs, and the folders of ia/corpus kept for
it (DEVELOPER_FOLDERS: ia/corpus/swig, SWIG's manual, filled by
fespp_ia.swig_docs). --fetpapi adds fetpapi's headers. None of it enters
the corpus without --developer: the application's index stays what it was.

    python -m fespp_ia.corpus --app <fespp-on-trame> --fesapi <fesapi> \\
        --fespp <fespp>/src --out ia/corpus_cache/chunks.jsonl
    python -m fespp_ia.corpus ... --fetpapi <fetpapi> --developer \\
        --out ia/corpus_cache/chunks-dev.jsonl

One JSON object per chunk: {"id", "source", "path", "title", "text"}.
Chunks are ~900 characters, cut on paragraph ends, with a 150-character
overlap; a C++ or Python docstring is one chunk with its declaration.
"""
import argparse
import ast
import json
import os
import re
import sys

CHUNK = 900
OVERLAP = 150
# a Doxygen block opens with exactly "/**" then a space or a newline: a
# "/****" banner is not one, and matching it would swallow all the code up
# to the next "*/"
_DOXY = re.compile(r"/\*\*(?=\s)(.*?)\*/\s*([^\n;{}]*)", re.S)
_STRIP = re.compile(r"^\s*\*\s?", re.M)
# the longest a Doxygen block may be; past it, the comment is cut at a line
# end (a safety net behind the opener rule)
_DOXY_CAP = 3000
# the class a header declares: "class Foo", "class DLL_IMPORT_OR_EXPORT Foo
# final : public Bar" -- not a forward declaration ("class Foo;") nor the
# word "class" of a comment ("Proxy class for an abstract...")
_CLASS_DECL = re.compile(r"\bclass\s+(?:\w+_EXPORT\s+|DLL_IMPORT_OR_EXPORT\s+)?(\w+)\s*(?:final)?\s*[:{]")
# headers that document nothing a reader asks about: fesapi's macros and
# the gsoap-generated stubs ("*** Enumeration Types ***" banners)
_CPP_SKIP = re.compile(r"^MacroDefinitions\.h$|Stub\.h$")
# a Markdown file under this size is one chunk whatever its headings (a
# short page of one-line sections stays whole)
_SMALL_MD = 2000
# working notes, not documentation: left out of the app's Markdown
_MD_SKIP = re.compile(r"^(TODO|CHANGELOG.*)\.md$", re.I)
# what a library's own Markdown says to who builds or uses it; its code of
# conduct and its pull-request template say nothing of the kind
_LIBRARY_MD = re.compile(r"^(README|BUILD|CONTRIBUTING)\.md$", re.I)
# a glossary bullet: "- **Term** — definition" (the wiki Glossary, EN and FR)
_GLOSSARY_BULLET = re.compile(r"^-\s+\*\*(.+?)\*\*\s*[—–:-]+\s*(.*)$")


def paragraphs_to_chunks(text, size=CHUNK, overlap=OVERLAP):
    """Chunks of about `size` characters, cut on paragraph ends; the tail
    of one chunk (`overlap`) begins the next, so a sentence cut in two is
    whole in one of them."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, cur = [], ""
    for p in paras:
        if len(p) > size * 2:
            # a paragraph too long on its own: cut on sentences
            for s in re.split(r"(?<=[.!?])\s+", p):
                if len(cur) + len(s) > size and cur:
                    out.append(cur)
                    cur = cur[-overlap:] + " " + s
                else:
                    cur = (cur + " " + s).strip()
            continue
        if len(cur) + len(p) > size and cur:
            out.append(cur)
            cur = cur[-overlap:] + "\n\n" + p
        else:
            cur = (cur + "\n\n" + p).strip()
    if cur:
        out.append(cur)
    return out


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as exc:
        print(f"[corpus] cannot read {path}: {exc}", file=sys.stderr)
        return ""


def markdown_sections(text, doc_title):
    """[(title, text)]: a Markdown document cut on its headings — a section
    is its heading and what follows up to the next heading of the same or
    a higher level, titled "document › heading"; a section too long is
    then chunked. A glossary entry becomes ONE chunk titled by its name."""
    lines = text.split("\n")
    sections, cur_title, cur = [], doc_title, []
    for line in lines:
        m = re.match(r"^(#{1,4})\s+(.+?)\s*$", line)
        if m:
            if cur and "".join(cur).strip():
                sections.append((cur_title, "\n".join(cur)))
            head = m.group(2).strip()
            cur_title = head if len(m.group(1)) == 1 else f"{doc_title} › {head}"
            cur = []
        else:
            cur.append(line)
    if cur and "".join(cur).strip():
        sections.append((cur_title, "\n".join(cur)))
    out = []
    for title, body in sections:
        pieces = paragraphs_to_chunks(body)
        for k, piece in enumerate(pieces):
            out.append((title if len(pieces) == 1 else f"{title} ({k + 1})", piece))
    return out


def glossary_entries(text, doc_title):
    """[(title, text)] of a glossary written as bullets, one entry per
    bullet titled by its term -- or None when the document is not shaped
    that way (fewer than four bullets in five lines). Cut by size, a
    glossary would hold a dozen terms per chunk, and a search for one term
    would bring its neighbours along."""
    entries, lines = [], 0
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _GLOSSARY_BULLET.match(stripped)
        if m:
            entries.append([m.group(1).strip(), m.group(2).strip()])
        elif entries and line.startswith((" ", "\t")):
            entries[-1][1] += " " + stripped      # a wrapped bullet
            continue
        lines += 1
    if len(entries) < 4 or len(entries) * 5 < lines * 4:
        return None
    return [(f"{doc_title} › {term}", f"{term} — {definition}") for term, definition in entries]


def markdown_document(text, name):
    """[(title, text)] of one Markdown file: a glossary of bullets one entry
    per term (glossary_entries), a small file one chunk whatever its
    headings, any other cut on its headings (markdown_sections)."""
    m = re.search(r"^#\s+(.+)$", text, re.M)
    doc_title = m.group(1).strip() if m else re.sub(r"\.md$", "", name, flags=re.I)
    if name.lower() == "glossary.md":
        entries = glossary_entries(text, doc_title)
        if entries:
            return entries
    if len(text) < _SMALL_MD:
        body = text if not m else text.replace(m.group(0), "", 1)
        return [(doc_title, body.strip())] if body.strip() else []
    return markdown_sections(text, doc_title)


def markdown_chunks(root, source, subdirs, one_level=(), only=None):
    """Every .md of the subfolders (markdown_document), and of the
    immediate subfolders of those named in `one_level` (doc/dev/widgets).
    TODO and CHANGELOG files are working notes, left out; with `only`, a
    compiled pattern, so is every file whose name it does not match."""
    for sub in subdirs:
        folder = os.path.join(root, sub)
        if not os.path.isdir(folder):
            continue
        folders = [folder]
        if sub in one_level:
            folders += sorted(p for p in (os.path.join(folder, d) for d in os.listdir(folder))
                              if os.path.isdir(p))
        for folder in folders:
            for name in sorted(os.listdir(folder)):
                if not name.endswith(".md") or _MD_SKIP.match(name) or (only and not only.match(name)):
                    continue
                path = os.path.join(folder, name)
                rel = os.path.relpath(path, root).replace("\\", "/")
                for title, chunk in markdown_document(_read(path), name):
                    yield {"source": source, "path": rel, "title": title, "text": f"{title}\n\n{chunk}"}


def python_docstrings(root, source, packages):
    """One chunk per documented module, class or function: the qualified
    name, the signature, the docstring."""
    for pkg in packages:
        top = os.path.join(root, pkg)
        for folder, _dirs, files in os.walk(top):
            if "__pycache__" in folder or "node_modules" in folder:
                continue
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                path = os.path.join(folder, name)
                rel = os.path.relpath(path, root).replace("\\", "/")
                modname = rel[:-3].replace("/", ".")
                try:
                    tree = ast.parse(_read(path))
                except SyntaxError as exc:
                    print(f"[corpus] {rel}: {exc}", file=sys.stderr)
                    continue
                doc = ast.get_docstring(tree)
                if doc and len(doc) > 60:
                    yield {"source": source, "path": rel, "title": modname,
                           "text": f"Module {modname}\n\n{doc}"}
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        d = ast.get_docstring(node)
                        if not d or len(d) < 60:
                            continue
                        args = ""
                        if not isinstance(node, ast.ClassDef):
                            args = "(" + ", ".join(a.arg for a in node.args.args) + ")"
                        yield {"source": source, "path": rel, "title": f"{modname}.{node.name}",
                               "text": f"{modname}.{node.name}{args}\n\n{d}"}


def cpp_owner(text, name):
    """The class a header documents, for the chunk titles: the file's stem
    when a class of that name is declared (_CLASS_DECL) or none is -- one
    class per header in fesapi and in fespp -- else the first declared
    class. Never the first "class" word of the file: that may be a forward
    declaration ("class AbstractHdfProxy;") or a word of a comment."""
    stem = os.path.splitext(name)[0]
    names = [m.group(1) for m in _CLASS_DECL.finditer(text)]
    return stem if stem in names or not names else names[0]


def cpp_doxygen(root, source, subdirs, suffixes=(".h",)):
    """One chunk per Doxygen block of the headers: the comment, then the
    declaration it documents (class, method, enum)."""
    for sub in subdirs:
        top = os.path.join(root, sub)
        for folder, _dirs, files in os.walk(top):
            for name in sorted(files):
                if not name.endswith(suffixes) or _CPP_SKIP.search(name):
                    continue
                path = os.path.join(folder, name)
                rel = os.path.relpath(path, root).replace("\\", "/")
                text = _read(path)
                owner = cpp_owner(text, name)
                for m in _DOXY.finditer(text):
                    body = _STRIP.sub("", m.group(1)).strip()
                    body = re.sub(r"@brief\s*", "", body)
                    if len(body) > _DOXY_CAP:
                        body = body[:_DOXY_CAP].rsplit("\n", 1)[0]
                    decl = " ".join(m.group(2).split())
                    if decl.startswith(("#", "//")):
                        decl = ""    # a class @brief above the #includes documents the class itself
                    # a block worth reading says something: not a
                    # constructor, a destructor, a one-line getter or a
                    # licence header
                    if len(body) < 120 or "= default" in decl or "~" in decl or "@param" == body[:6] \
                            or body.startswith(("Copyright", "Licensed", "Constructor", "Destructor")) \
                            or "Constructor." in body[:40] or "Only to be used in partial transfer" in body:
                        continue
                    title = f"{owner}: {decl[:90]}" if decl else owner
                    yield {"source": source, "path": rel, "title": title,
                           "text": f"{owner} — {decl}\n\n{body}" if decl else f"{owner}\n\n{body}"}


def lines_to_chunks(lines, size=CHUNK):
    """Chunks of about `size` characters cut at line ends, without overlap:
    for code and lists, where a cut on sentences would break a statement."""
    out, cur, n = [], [], 0
    for line in lines:
        if cur and n + len(line) + 1 > size:
            out.append("\n".join(cur))
            cur, n = [], 0
        cur.append(line)
        n += len(line) + 1
    if cur and "".join(cur).strip():
        out.append("\n".join(cur))
    return out


# What each SWIG directive does, in one line, said at the head of its chunk:
# a question in plain words ("how does a C++ exception reach Python?") then
# meets the directive that answers it, and the reader of the extract knows
# what he is looking at.
_SWIG_DIRECTIVES = {
    "module": "names the module the wrapper builds, with its options (directors)",
    "include": "reads another interface file, or a file of SWIG's library, into this one",
    "import": "reads the declarations of another interface file without wrapping them again",
    "nspace": "keeps the C++ namespace of a class in the target language (a Java package, a C# namespace) "
              "instead of putting every class in one scope",
    "nspacemove": "puts a class in another namespace of the target language than its C++ one",
    "rename": "gives a C++ declaration another name in the target language",
    "ignore": "leaves a C++ declaration out of the wrapper",
    "template": "instantiates a C++ template under a name the target language can use",
    "typemap": "the code SWIG generates to convert a C++ type to or from the target language",
    "apply": "gives a type the typemaps of another one",
    "clear": "removes the typemaps of a type",
    "extend": "adds methods, or typemaps, to a C++ class in the wrapper only",
    "feature": "sets a customization feature on a declaration (director, nspace, python:annotations...)",
    "exception": "the code around every wrapped call: it turns a C++ exception into an error of the target language",
    "fragment": "a piece of code written once in the wrapper, when a typemap asks for it",
    "define": "a SWIG macro, expanded where it is used",
    "inline": "C++ code compiled into the wrapper and wrapped as well",
    "pythoncode": "Python code added to the generated module",
    "array_class": "wraps a C array of a type as a class of the target language: Name(n), then getitem(i) and "
                   "setitem(i, value)",
    "array_functions": "wraps a C array of a type as functions: new_Name(n), Name_getitem(a, i), "
                       "Name_setitem(a, i, value), delete_Name(a)",
    "nodefaultctor": "no default constructor is generated (for the class named, or for every class that follows)",
    "newobject": "the target language owns the object the function returns, and frees it",
    "shared_ptr": "the class is held by std::shared_ptr in the wrapper",
    "warnfilter": "silences a SWIG warning for a declaration",
    "javaconst": "Java constants are generated as compile-time constants",
    "csconst": "C# constants are generated as compile-time constants",
    "pragma": "an instruction for one target language's module (code or imports added to the generated module)",
}
_SWIG_LINE = re.compile(r"^\s*%(\w+)")
_SWIG_PP = re.compile(r"^\s*#\s*(ifdef|ifndef|if|elif|else|endif)\b(.*)$")
# the longest a directive may run; past it the scan gives up on its end (a
# safety net behind the count of braces)
_SWIG_CAP = 300
# the examples of %nspace quoted in its summary
_NSPACE_EXAMPLES = 12
# the longest comment kept above a directive
_SWIG_COMMENT = 300


def _swig_depth(line):
    """(parentheses, braces) the line opens minus those it closes, outside
    its strings and its // comment. "%{" and "%}" count as the braces they
    hold."""
    par = brace = 0
    quoted, i = False, 0
    while i < len(line):
        c = line[i]
        if quoted:
            if c == "\\":
                i += 1
            elif c == '"':
                quoted = False
        elif c == '"':
            quoted = True
        elif line.startswith("//", i):
            break
        elif c == "(":
            par += 1
        elif c == ")":
            par -= 1
        elif c == "{":
            brace += 1
        elif c == "}":
            brace -= 1
        i += 1
    return par, brace


def _swig_condition(kind, rest):
    """A preprocessor condition as it reads: "SWIGJAVA || SWIGCSHARP"."""
    rest = rest.split("//")[0].strip()
    if kind == "ifndef":
        return f"not {rest}"
    return re.sub(r"defined\s*\(\s*(\w+)\s*\)", r"\1", rest)


def swig_directives(text):
    """[(name, condition, comment, lines)] of a SWIG interface file, in
    order: every "%directive" with the preprocessor conditions it sits
    under ("SWIGPYTHON", "not (SWIGJAVA)"; "" when none), the comment right
    above it and its lines -- one line, or as many as its parentheses and
    braces span (a %typemap, an %extend, a %define up to its %enddef).

    Left out: the "%{ ... %}" blocks (the #includes of the wrapper) and
    everything that is not a directive -- the class declarations and the
    enumerations, which say the headers again."""
    lines = text.split("\n")
    out, stack, comment = [], [], []
    in_comment = False
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()
        i += 1
        if in_comment:
            comment.append(s.strip("*/ \t"))
            in_comment = "*/" not in s
            continue
        if s.startswith("/*"):
            comment = [s.strip("/* \t")]
            in_comment = "*/" not in s
            continue
        if s.startswith("//"):
            comment.append(s.lstrip("/ \t"))
            continue
        pp = _SWIG_PP.match(line)
        if pp:
            kind, rest = pp.group(1), pp.group(2)
            if kind in ("if", "ifdef", "ifndef"):
                cond = _swig_condition(kind, rest)
                stack.append({"seen": [cond], "now": cond})
            elif kind == "endif":
                if stack:
                    stack.pop()
            elif stack:
                # an #else or #elif holds when no branch before it did
                top = stack[-1]
                nots = " and ".join(f"not ({c})" for c in top["seen"])
                if kind == "elif":
                    cond = _swig_condition(kind, rest)
                    top["now"] = f"{nots} and {cond}"
                    top["seen"].append(cond)
                else:
                    top["now"] = nots
            comment = []
            continue
        m = _SWIG_LINE.match(line)
        if s.startswith("%{"):
            while i < len(lines) and "%}" not in lines[i - 1]:
                i += 1
            comment = []
            continue
        if not m or m.group(1) == "enddef":
            comment = []    # a comment belongs to the directive right under it
            continue
        name = m.group(1)
        stmt = [line]
        if name == "define":
            while i < len(lines) and len(stmt) < _SWIG_CAP and not re.match(r"^\s*%enddef\b", stmt[-1]):
                stmt.append(lines[i])
                i += 1
        else:
            par, brace = _swig_depth(line)
            code = line.split("//")[0].rstrip()
            if par == 0 and brace == 0 and code[-1:] not in (";", '"', "}") and i < len(lines) \
                    and lines[i].lstrip().startswith(("{", "%{")):
                # the body opens on the line after ("%typemap(in) T" then "{")
                stmt.append(lines[i])
                par, brace = _swig_depth(lines[i])
                i += 1
            while (par > 0 or brace > 0) and i < len(lines) and len(stmt) < _SWIG_CAP:
                stmt.append(lines[i])
                p, b = _swig_depth(lines[i])
                par, brace = par + p, brace + b
                i += 1
        levels = [level["now"] for level in stack]
        if len(levels) > 1:
            levels = [f"({c})" if " " in c else c for c in levels]
        out.append((name, " and ".join(levels), " ".join(c for c in comment if c), stmt))
        comment = []
    return out


def _dedent(lines):
    """The lines without the indentation they share, tabs as four spaces."""
    lines = [ln.expandtabs(4).rstrip() for ln in lines]
    pad = min((len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()), default=0)
    return [ln[pad:] for ln in lines]


def swig_file_chunks(text, name):
    """[(title, text)] of one SWIG interface file. A directive that spans
    several lines (a %typemap, an %extend, the %exception handler) is one
    chunk; the one-line directives are gathered by kind and by condition
    (every %template, every %rename under SWIGJAVA...), cut by size; the
    %nspace lines, one per class, are summed up -- the rule matters, not
    the list. Each chunk opens with what the directive does and the
    condition it sits under."""
    out, groups = [], {}
    for directive, cond, comment, stmt in swig_directives(text):
        if len(stmt) == 1:
            groups.setdefault((directive, cond), []).append(stmt[0].strip())
            continue
        head = _swig_head(directive, name, cond)
        # titled by what the directive applies to: its text up to the body it
        # opens ("%typemap(cscode) DataObjectRepository", "%exception"); a
        # macro by its first line
        flat = " ".join((stmt[0] if directive == "define" else " ".join(stmt)).split())
        first = re.split(r"\s*%?\{", flat, maxsplit=1)[0]
        # the comment above, unless it is a banner (a licence, a section rule)
        body = ([f"// {comment}"] if comment and len(comment) <= _SWIG_COMMENT else []) + _dedent(stmt)
        title = f"SWIG › {name} › {first[:90]}"
        pieces = lines_to_chunks(body, _DOXY_CAP)
        for k, piece in enumerate(pieces):
            out.append((title if len(pieces) == 1 else f"{title} ({k + 1})", f"{head}\n\n{piece}"))
    for (directive, cond), rows in groups.items():
        head = _swig_head(directive, name, cond)
        title = f"SWIG › {name} › %{directive}" + (f" ({cond})" if cond else "")
        if directive == "nspace":
            spaces = sorted({r.split("::")[0].split()[-1] for r in rows if "::" in r})
            rows = [f"{len(rows)} classes, of the namespaces {', '.join(spaces)}; for instance:"] \
                + rows[:_NSPACE_EXAMPLES]
        pieces = lines_to_chunks(rows)
        for k, piece in enumerate(pieces):
            out.append((title if len(pieces) == 1 else f"{title} ({k + 1})", f"{head}\n\n{piece}"))
    return out


def _swig_head(directive, name, cond):
    """The first lines of a SWIG chunk: the directive and what it does, the
    file, the condition."""
    does = _SWIG_DIRECTIVES.get(directive)
    head = f"SWIG directive %{directive}" + (f": {does}." if does else ".")
    return head + f"\nInterface file {name}, " + (f"only when {cond}." if cond else "whatever the target language.")


def swig_chunks(root, subdirs, source="swig"):
    """The SWIG interface files (.i, and .i.in, CMake's templates) of the
    subfolders: swig_file_chunks of each. A .i whose .i.in is read too is
    CMake's output of it and is left out."""
    found = {}
    for sub in subdirs:
        top = os.path.join(root, sub)
        for folder, _dirs, files in os.walk(top):
            for name in sorted(files):
                if name.endswith((".i", ".i.in")):
                    found.setdefault(name, os.path.join(folder, name))
    for name in sorted(found):
        if name.endswith(".i") and name + ".in" in found:
            continue
        path = found[name]
        rel = os.path.relpath(path, root).replace("\\", "/")
        shown = name[:-3] if name.endswith(".in") else name
        for title, chunk in swig_file_chunks(_read(path), shown):
            yield {"source": source, "path": rel, "title": title, "text": f"{title}\n\n{chunk}"}


# where a function starts in an example: "def name(" or "class Name" in
# Python, in C++ a line at the margin that opens a parameter list and does
# not end a statement ("void serializeGrid(Repo * repo)", "bool Foo::bar(")
_PY_DEF = re.compile(r"^(?:def|class)\s+(\w+)")
_CPP_DEF = re.compile(r"^[A-Za-z_][\w:<>*&, ]*?[\s*&]([\w:~]+)\s*\([^;]*$")
_CPP_NOT_DEF = re.compile(r"^(if|for|while|switch|return|else|do|using|typedef|namespace|struct|class|enum)\b")
_EXAMPLE_SUFFIXES = (".py", ".cpp", ".h", ".ipynb")


def source_blocks(text, python):
    """[(name, lines)] of a source file cut where its functions start
    (_PY_DEF, _CPP_DEF); what stands before the first one -- the imports,
    the #includes -- is the block named ""."""
    blocks, name, cur = [], "", []
    in_comment = False
    for line in text.split("\n"):
        s = line.strip()
        start = None
        if in_comment:
            in_comment = "*/" not in s
        elif not python and s.startswith("/*"):
            in_comment = "*/" not in s
        elif python:
            m = _PY_DEF.match(line)
            start = m.group(1) if m else None
        elif not _CPP_NOT_DEF.match(line):
            m = _CPP_DEF.match(line)
            start = m.group(1) if m else None
        if start:
            if "".join(cur).strip():
                blocks.append((name, cur))
            name, cur = start, []
        cur.append(line.rstrip())
    if "".join(cur).strip():
        blocks.append((name, cur))
    return blocks


def notebook_lines(text):
    """The lines of a Jupyter notebook worth reading: its Markdown cells and
    the source of its code cells, in order, without the outputs."""
    try:
        cells = json.loads(text).get("cells", [])
    except (ValueError, AttributeError):
        return []
    lines = []
    for cell in cells:
        if cell.get("cell_type") not in ("markdown", "code"):
            continue
        src = cell.get("source", "")
        src = "".join(src) if isinstance(src, list) else str(src)
        if src.strip():
            lines += src.rstrip().split("\n") + [""]
    return lines


def example_chunks(root, label, subdirs, source="examples"):
    """The example programs of a library (.py, .cpp, .h, .ipynb under the
    subfolders): each function is cut by size at line ends and titled
    "<label> example › <file> › <function>", so a question "how do I write
    a grid?" meets the code that does it; a notebook is read cell after
    cell. The licence banner at the top of a file is left out."""
    for sub in subdirs:
        top = os.path.join(root, sub)
        for folder, _dirs, files in os.walk(top):
            for name in sorted(files):
                if not name.endswith(_EXAMPLE_SUFFIXES):
                    continue
                path = os.path.join(folder, name)
                rel = os.path.relpath(path, root).replace("\\", "/")
                text = _read(path)
                if name.endswith(".ipynb"):
                    blocks = [("", notebook_lines(text))]
                else:
                    text = re.sub(r"\A\s*/\*.*?\*/", "", text, count=1, flags=re.S)
                    blocks = source_blocks(text, name.endswith(".py"))
                for block, lines in blocks:
                    title = f"{label} example › {rel}" + (f" › {block}" if block else "")
                    pieces = lines_to_chunks([ln.expandtabs(4) for ln in lines])
                    for k, piece in enumerate(pieces):
                        t = title if len(pieces) == 1 else f"{title} ({k + 1})"
                        yield {"source": source, "path": rel, "title": t, "text": f"{t}\n\n{piece}"}


# paraview.simple's generated docstring: every proxy function ends with it,
# and most of them say nothing else
_PV_BOILERPLATE = re.compile(r"\s*This function creates a new proxy\..*$", re.S)


def jsonl_chunks(path, source=None):
    """Chunks already made (the ParaView extraction), passed through --
    minus the generated boilerplate, and minus the rows that said nothing
    else (a signature alone is under 40 characters of body)."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            row["text"] = _PV_BOILERPLATE.sub("", row.get("text", "")).rstrip()
            if len(row["text"].partition("\n\n")[2].strip()) < 40:
                continue    # the signature line and nothing under it
            if source:
                row["source"] = source
            yield row


def catalogue_chunks(path):
    """One chunk per command of the assistant, from the catalogue hints
    (ia/corpus_cache/catalogue-hints.json: name, fr, en descriptions) --
    so /v1/ask can say what the assistant can do. The slots come from the
    sibling catalogue.json when it is there (the hints file carries none)."""
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        commands = json.load(f)
    slots = {}
    sibling = os.path.join(os.path.dirname(path), "catalogue.json")
    if os.path.isfile(sibling) and os.path.abspath(sibling) != os.path.abspath(path):
        with open(sibling, encoding="utf-8") as f:
            slots = {c.get("name"): c.get("slots") for c in json.load(f) if isinstance(c, dict)}
    for c in commands:
        name = c.get("name")
        if not name:
            continue
        lines = [f"Commande de l'assistant / assistant command: {name}"]
        if c.get("fr"):
            lines.append(f"FR : {c['fr'].strip()}")
        if c.get("en"):
            lines.append(f"EN: {c['en'].strip()}")
        s = c.get("slots") if c.get("slots") is not None else slots.get(name)
        if s:
            lines.append("Paramètres / slots: " + ", ".join(s))
        title = f"Assistant › {name}"
        yield {"source": "docs", "path": f"catalogue#{name}", "title": title,
               "text": f"{title}\n\n" + "\n".join(lines)}


_XS = "{http://www.w3.org/2001/XMLSchema}"
_STANDARDS = (("resqml", "RESQML"), ("common", "Energistics common"), ("etp", "ETP"),
              ("witsml", "WITSML"), ("prodml", "PRODML"), ("eml", "Energistics common"))


def _xsd_doc(node):
    """The xs:documentation text right under `node`'s xs:annotation."""
    parts = []
    ann = node.find(f"{_XS}annotation")
    if ann is not None:
        for d in ann.findall(f"{_XS}documentation"):
            parts.append("".join(d.itertext()))
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def _xsd_label(root, name):
    """"RESQML v2.2 (XSD)": the standard from the target namespace, the
    version from the schema's own version attribute."""
    ns = (root.get("targetNamespace") or "").lower()
    std = next((label for key, label in _STANDARDS if key in ns), None)
    if std is None:
        std = ns.rstrip("/").rsplit("/", 1)[-1] or os.path.splitext(os.path.basename(name))[0]
    version = root.get("version")
    return f"{std} v{version} (XSD)" if version else f"{std} (XSD)"


def _xsd_field(el):
    """One line for an xs:element or xs:attribute of a type."""
    name = el.get("name") or el.get("ref") or "?"
    kind = el.get("type") or ""
    lo, hi = el.get("minOccurs"), el.get("maxOccurs")
    card = ""
    if el.tag == f"{_XS}attribute":
        card = "required" if el.get("use") == "required" else ""
    elif lo is not None or hi is not None:
        card = f"{lo or '1'}..{'*' if hi == 'unbounded' else (hi or '1')}"
    head = name + (f" ({', '.join(x for x in (kind, card) if x)})" if kind or card else "")
    doc = _xsd_doc(el)
    return f"- {head}" + (f" : {doc}" if doc else "")


# Energistics common's plumbing of units: one measure type or unit list per
# quantity, the bulk of its types -- units are explained by the Unit of
# Measure Usage Guide, these lists only crowd the search.
_XSD_SKIP_FILES = {"quantityclass.xsd", "measuretype.xsd"}
# an enumeration longer than this with almost no documented value (the unit
# symbols) is summed up in one chunk
_ENUM_SUMMARY = 150


def xsd_chunks(data, name):
    """[(title, text)] of one XSD file: one entry per top-level type or
    element that says something -- its definition, its parent type, its
    fields (name, type, cardinality, documentation) and, for an
    enumeration, every value with its own documentation. A long type (the
    big enumerations of property kinds) is cut into several chunks. Left
    out: the unit plumbing of Energistics common (_XSD_SKIP_FILES) and the
    "...Ext" types that only extend an enumeration by the standard pattern."""
    import xml.etree.ElementTree as ET
    if os.path.basename(name).lower() in _XSD_SKIP_FILES:
        return []
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        print(f"[corpus] {name}: not a readable XSD ({exc})", file=sys.stderr)
        return []
    if root.tag != f"{_XS}schema":
        return []
    label = _xsd_label(root, name)
    out = []
    for node in root:
        tag = node.tag.replace(_XS, "")
        tname = node.get("name")
        if not tname or tag not in ("complexType", "simpleType", "element", "group", "attributeGroup"):
            continue
        doc = _xsd_doc(node)
        lines = []
        if tag == "complexType" or tag in ("group", "attributeGroup"):
            base = None
            for ext in node.iter():
                if ext.tag in (f"{_XS}extension", f"{_XS}restriction") and ext.get("base"):
                    base = ext.get("base")
                    break
            abstract = " abstract" if node.get("abstract") == "true" else ""
            lines.append(f"{tname} ({tag}{abstract}" + (f", derives from {base})" if base else ")"))
            fields = [el for el in node.iter() if el.tag in (f"{_XS}element", f"{_XS}attribute")]
            if doc:
                lines.append(doc)
            if fields:
                lines.append("Fields:")
                lines.extend(_xsd_field(el) for el in fields)
        elif tag == "simpleType":
            union = node.find(f"{_XS}union")
            if union is not None and "EnumExtensionPattern" in (union.get("memberTypes") or ""):
                continue   # "...Ext": the enumeration or any string -- the pattern, nothing to learn
            rest = node.find(f"{_XS}restriction")
            base = rest.get("base") if rest is not None else None
            lines.append(f"{tname} (simpleType" + (f", restriction of {base})" if base else ")"))
            if doc:
                lines.append(doc)
            enums = rest.findall(f"{_XS}enumeration") if rest is not None else []
            documented = sum(1 for e in enums if _xsd_doc(e))
            if len(enums) > _ENUM_SUMMARY and documented < len(enums) // 5:
                lines.append(f"{len(enums)} values, for instance: "
                             + ", ".join(e.get("value") for e in enums[:40]) + ", …")
            elif enums:
                lines.append("Values:")
                for e in enums:
                    d = _xsd_doc(e)
                    lines.append(f"- {e.get('value')}" + (f" : {d}" if d else ""))
            if union is not None and union.get("memberTypes"):
                lines.append("Union of: " + union.get("memberTypes"))
        else:  # a top-level element: worth a chunk only when documented
            if not doc:
                continue
            lines.append(f"{tname} (element" + (f" of type {node.get('type')})" if node.get("type") else ")"))
            lines.append(doc)
        if len(lines) <= 1 and not doc:
            continue
        title = f"{label} › {tname}"
        pieces = paragraphs_to_chunks("\n\n".join(lines))
        for k, piece in enumerate(pieces):
            out.append((title if len(pieces) == 1 else f"{title} ({k + 1})", piece))
    return out


def _avro_type(t):
    """A readable Avro type: short names, arrays, maps and unions."""
    if isinstance(t, str):
        return re.sub(r"^Energistics\.Etp\.v\d+\.(Datatypes\.)?", "", t)
    if isinstance(t, list):
        return " | ".join(_avro_type(x) for x in t)
    if isinstance(t, dict):
        kind = t.get("type")
        if kind == "array":
            return f"array of {_avro_type(t.get('items'))}"
        if kind == "map":
            return f"map of {_avro_type(t.get('values'))}"
        if t.get("name"):
            return _avro_type(t["name"])
        return _avro_type(kind)
    return str(t)


def avro_chunks(data, name):
    """[(title, text)] of one Avro schema (.avsc) of ETP: one chunk per
    record or enum -- for a message, its protocol, message type and sender
    role, then its fields and their types. ETP 1.2's schemas carry no
    documentation: the specification PDF explains, these say exactly what a
    message holds."""
    try:
        d = json.loads(data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data)
    except ValueError as exc:
        print(f"[corpus] {name}: not a readable Avro schema ({exc})", file=sys.stderr)
        return []
    out = []
    for s in d if isinstance(d, list) else [d]:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        ns = s.get("namespace", "")
        m = re.search(r"Etp\.v(\d)(\d)", ns)
        label = f"ETP v{m.group(1)}.{m.group(2)} (Avro)" if m else "Avro"
        short = re.sub(r"^Energistics\.Etp\.v\d+\.?", "", ns)
        title = f"{label} › {short + '.' if short else ''}{s['name']}"
        head = f"{s['name']} ({s.get('type', '?')}"
        if "protocol" in s:
            head += (f", ETP message: protocol {s['protocol']}, message type {s.get('messageType', '?')}, "
                     f"sent by the {s.get('senderRole', '?')}, roles {s.get('protocolRoles', '?')}")
            if s.get("multipartFlag"):
                head += ", multipart"
        lines = [head + ")"]
        if s.get("doc"):
            lines.append(s["doc"])
        if s.get("type") == "enum":
            lines.append("Values: " + ", ".join(s.get("symbols", [])))
        fields = s.get("fields") or []
        if fields:
            lines.append("Fields:")
            for f in fields:
                line = f"- {f.get('name')} ({_avro_type(f.get('type'))})"
                if "default" in f:
                    line += f", default {json.dumps(f['default'])}"
                if f.get("doc"):
                    line += f" : {f['doc']}"
                lines.append(line)
        pieces = paragraphs_to_chunks("\n\n".join(lines))
        for k, piece in enumerate(pieces):
            out.append((title if len(pieces) == 1 else f"{title} ({k + 1})", piece))
    return out


# in an official package, what only adds noise: release notes, read-me's,
# known-issue lists, a tool's how-to; and the Technical Reference Guide when
# the package's own XSD are indexed (the guide is generated from them)
_SKIP_DOC = re.compile(r"release.?notes|read.?me|known.?issues|how to import", re.I)
_REFERENCE_GUIDE = re.compile(r"technical.?reference.?guide", re.I)


def pdf_title(name):
    """The title of a PDF's chunks: its file name, cleaned
    ("ETP_Specification_v1.2.pdf" -> "ETP Specification v1.2"). Not the
    metadata title, which can name nothing (the ETP specification's says
    "Energistics Document"): the file name is chosen when the PDF is
    fetched or dropped."""
    stem = os.path.basename(name)
    if stem.lower().endswith(".pdf"):
        stem = stem[:-4]
    return re.sub(r"[_\s]+", " ", stem).strip() or name


def _pdf_chunks(fileobj, name):
    """[(path suffix, title, text)] of a PDF, page by page."""
    try:
        from pypdf import PdfReader
    except ImportError:
        print(f"[corpus] {name}: pypdf is not installed, skipped", file=sys.stderr)
        return []
    try:
        reader = PdfReader(fileobj)
    except Exception as exc:
        print(f"[corpus] {name}: {exc}", file=sys.stderr)
        return []
    doc_title = pdf_title(name)
    out = []
    for p, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            print(f"[corpus] {name} p.{p}: {exc}", file=sys.stderr)
            continue
        for k, chunk in enumerate(paragraphs_to_chunks(text)):
            out.append((f"#p{p}", f"{doc_title} › p.{p} ({k + 1})", chunk))
    return out


def _dropped_one(name, rel, data_or_path, source):
    """The chunks of one dropped document -- a path on disk, or the bytes of
    a member of a zip."""
    low = name.lower()
    is_bytes = isinstance(data_or_path, (bytes, bytearray))
    if _SKIP_DOC.search(name):
        return

    def text():
        if is_bytes:
            return data_or_path.decode("utf-8", errors="replace")
        return _read(data_or_path)

    if low.endswith(".md"):
        for title, chunk in markdown_document(text(), name):
            yield {"source": source, "path": rel, "title": title, "text": f"{title}\n\n{chunk}"}
    elif low.endswith(".txt"):
        for k, chunk in enumerate(paragraphs_to_chunks(text())):
            yield {"source": source, "path": rel, "title": f"{name} ({k + 1})", "text": chunk}
    elif low.endswith(".xsd") or low.endswith(".avsc"):
        data = data_or_path if is_bytes else open(data_or_path, "rb").read()
        extract = xsd_chunks if low.endswith(".xsd") else avro_chunks
        for title, chunk in extract(data, name):
            yield {"source": source, "path": rel, "title": title, "text": f"{title}\n\n{chunk}"}
    elif low.endswith(".pdf"):
        import io
        fileobj = io.BytesIO(data_or_path) if is_bytes else data_or_path
        for suffix, title, chunk in _pdf_chunks(fileobj, name):
            yield {"source": source, "path": rel + suffix, "title": title, "text": f"{title}\n\n{chunk}"}
    elif low.endswith(".zip") and not is_bytes:
        import zipfile
        try:
            with zipfile.ZipFile(data_or_path) as z:
                members = sorted(z.namelist())
                has_xsd = any(m.lower().endswith(".xsd") for m in members)
                for member in members:
                    base = os.path.basename(member)
                    if not base or not base.lower().endswith((".md", ".txt", ".xsd", ".pdf", ".avsc")):
                        continue
                    if has_xsd and _REFERENCE_GUIDE.search(base):
                        continue   # generated from the XSD of the same package, read above
                    yield from _dropped_one(base, f"{rel}!/{member}", z.read(member), source)
        except zipfile.BadZipFile as exc:
            print(f"[corpus] {rel}: {exc}", file=sys.stderr)


_ENERGISTICS_ZIP = re.compile(r"resqml|energistics|energyml|epc|witsml|prodml|common", re.I)


def source_of(path, default="docs"):
    """The source label of a dropped document, from where it sits: the
    search ranks and filters by it (rag.SOURCE_BOOST; the glossary of a
    command reads only "docs" and "pwls", server.GLOSSARY_SOURCES). ETP --
    the protocol, pure network technique -- is kept apart ("etp"): its many
    chunks would crowd the answers, and its streaming "channel" is not a
    river channel. The official Energistics documentation is "energistics",
    the geology wikis "geologie", the PWLS definitions of quantities
    "pwls", the ParaView filter documentation "paraview", the OSDU data
    definitions (the platform's vocabulary, no lead in the ranking) "osdu",
    SWIG's manual "swig" (the label of the interface files too);
    the project's own documents (the glossary...) stay "docs"."""
    parts = [p.lower() for p in re.split(r"[\\/]+", path) if p]
    name = parts[-1] if parts else ""
    for folder in ("geologie", "pwls", "paraview", "osdu", "swig"):
        if folder in parts:
            return folder
    if re.search(r"(^|[^a-z])etp([^a-z]|$)", name) or any(re.match(r"etp([^a-z]|$)", p) for p in parts):
        return "etp"
    if "energistics" in parts or (name.endswith(".zip") and _ENERGISTICS_ZIP.search(name)):
        return "energistics"
    return default


# the folders of ia/corpus only the developer's corpus reads: SWIG's manual
# answers who writes a wrapper, and would only crowd the answers of who
# asks about a reservoir
DEVELOPER_FOLDERS = ("swig",)


def dropped_files(folder, source="docs", developer=False):
    """What the reader dropped in ia/corpus, in every subfolder: .md cut on
    its headings, .txt by paragraphs, .pdf page by page (pypdf), .xsd one
    chunk per documented type (xsd_chunks), .avsc one chunk per ETP message
    (avro_chunks), and a .zip -- an official Energistics package as
    downloaded -- read inside, member by member. Release notes, read-me's
    and the like are left out (_SKIP_DOC), and so are the DEVELOPER_FOLDERS
    unless `developer`."""
    if not os.path.isdir(folder):
        return
    top = os.path.abspath(folder)
    for dirpath, dirnames, filenames in os.walk(folder):
        if not developer and os.path.abspath(dirpath) == top:
            dirnames[:] = [d for d in dirnames if d.lower() not in DEVELOPER_FOLDERS]
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, folder).replace("\\", "/")
            yield from _dropped_one(name, rel, path, source_of(os.path.abspath(path), source))


def build(app=None, fesapi=None, fespp=None, paraview_jsonl=None, dropped=None, catalogue=None,
          duplicates=None, fetpapi=None, developer=False):
    """Every chunk of every source given, numbered. A text already seen in
    the same source is dropped (fesapi documents many classes word for word
    in both resqml2_0_1 and resqml2_2); `duplicates`, a dict, counts them by
    source. `developer` adds what a developer of fesapi and fetpapi asks
    about -- their SWIG interfaces, examples and READMEs, and the
    DEVELOPER_FOLDERS of `dropped`."""
    n = 0
    gens = []
    if app:
        gens.append(markdown_chunks(app, "fespp_on_trame",
                                    ("doc/wiki", "doc/wiki-fr", "doc/EN", "doc/FR", "doc/dev", "."),
                                    one_level=("doc/dev",)))
        gens.append(python_docstrings(app, "fespp_on_trame", ("fespp_on_trame",)))
        widgets = os.path.join(app, "widgets")
        if os.path.isdir(widgets):
            gens.append(markdown_chunks(widgets, "fespp_on_trame", sorted(os.listdir(widgets))))
    if fesapi:
        gens.append(cpp_doxygen(fesapi, "fesapi", ("src",)))
    if fespp:
        from fespp_ia.fespp_docs import fespp_chunks
        gens.append(cpp_doxygen(fespp, "fespp", ("Plugin",), (".h", ".cxx")))
        gens.append(fespp_chunks(fespp))
    if fetpapi:
        gens.append(cpp_doxygen(fetpapi, "fetpapi", ("src",)))
    if developer:
        for root, library in ((fesapi, "fesapi"), (fetpapi, "fetpapi")):
            if root:
                gens.append(swig_chunks(root, ("swig", "cmake")))
                gens.append(example_chunks(root, library, ("example", "python/example")))
                gens.append(markdown_chunks(root, library, (".", "python", "src/etp"), only=_LIBRARY_MD))
    if paraview_jsonl:
        gens.append(jsonl_chunks(paraview_jsonl, "paraview"))
    if catalogue:
        gens.append(catalogue_chunks(catalogue))
    if dropped:
        gens.append(dropped_files(dropped, developer=developer))
    seen = {}
    for gen in gens:
        for row in gen:
            texts = seen.setdefault(row["source"], set())
            if row["text"] in texts:
                if duplicates is not None:
                    duplicates[row["source"]] = duplicates.get(row["source"], 0) + 1
                continue
            texts.add(row["text"])
            n += 1
            row["id"] = n
            yield row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--app")
    ap.add_argument("--fesapi")
    ap.add_argument("--fespp")
    ap.add_argument("--fetpapi", help="a fetpapi source tree: its headers")
    ap.add_argument("--developer", action="store_true",
                    help="the developer's corpus: also the SWIG interfaces, examples and READMEs of fesapi and "
                         "fetpapi, and SWIG's manual (ia/corpus/swig)")
    ap.add_argument("--paraview", help="the paraview_simple.jsonl extracted in the app image")
    ap.add_argument("--catalogue", help="the assistant's catalogue-hints.json: one chunk per command")
    ap.add_argument("--dropped", help="the folder of documents dropped by the reader (ia/corpus)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    counts, duplicates = {}, {}
    with open(a.out, "w", encoding="utf-8") as f:
        for row in build(a.app, a.fesapi, a.fespp, a.paraview, a.dropped, a.catalogue, duplicates,
                         fetpapi=a.fetpapi, developer=a.developer):
            counts[row["source"]] = counts.get(row["source"], 0) + 1
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("[corpus]", ", ".join(f"{k} {v}" for k, v in counts.items()), "->", a.out)
    if duplicates:
        print("[corpus] duplicates dropped:", ", ".join(f"{k} {v}" for k, v in duplicates.items()))


if __name__ == "__main__":
    main()
