"""SWIG's manual as the developer's corpus reads it: one Markdown file per
chapter, the headings with the manual's section numbers, the listings as
indented code, the chapter's table of contents left out."""
from fespp_ia.corpus import markdown_document
from fespp_ia.swig_docs import CHAPTERS, chapter_markdown

CHAPTER = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN">
<html><head><title>SWIG and Python</title><style>p { margin: 0 }</style></head>
<body bgcolor="#ffffff">
<H1><a name="Python">33 SWIG and Python</a></H1>
<!-- INDEX -->
<div class="sectiontoc">
<ul>
<li><a href="#Python_nn2">Overview</a>
<li><a href="#Python_nn3">Preliminaries</a>
<ul>
<li><a href="#Python_nn4">Running SWIG</a>
</ul>
</ul>
</div>
<!-- INDEX -->

<p>
This chapter describes SWIG's support of Python.
</p>

<H2><a name="Python_nn3">33.2 Preliminaries</a></H2>
<H3><a name="Python_nn4">33.2.1 Running SWIG</a></H3>

<p>
Suppose that you defined a SWIG module such as
the following, in a <tt>.i</tt> file:
</p>

<div class="code">
<pre>
/* File: example.i */
%module example

%{
#include "example.h"
%}
int fact(int n) { return n &lt; 2 ? 1 : n; }
</pre>
</div>

<ul>
<li>the <tt>-python</tt> option
<li>the <tt>-c++</tt> option
</ul>

<table><tr><th>C type</th><th>Python</th></tr><tr><td>int</td><td>int</td></tr></table>
</body></html>"""

URL = "https://www.swig.org/Doc4.4/Python.html"


def test_a_chapter_keeps_its_section_numbers_its_listings_and_drops_its_contents():
    md = chapter_markdown(CHAPTER, "4.4", URL)
    assert md == """# SWIG 4.4 manual — 33 SWIG and Python

Source : SWIG 4.4 Documentation, https://www.swig.org/Doc4.4/Python.html — licence GPL-3.0-or-later

This chapter describes SWIG's support of Python.

## 33.2 Preliminaries

### 33.2.1 Running SWIG

Suppose that you defined a SWIG module such as the following, in a .i file:

    /* File: example.i */
    %module example

    %{
    #include "example.h"
    %}
    int fact(int n) { return n < 2 ? 1 : n; }

- the -python option

- the -c++ option

C type | Python

int | int
"""


def test_a_page_without_a_chapter_title_gives_nothing():
    assert chapter_markdown("<html><body><p>Not found</p></body></html>", "4.4", URL) == ""


def test_the_chunks_of_a_chapter_are_titled_by_the_manual_the_chapter_and_the_section():
    """A long chapter is cut on its headings: the title of a chunk says
    where in the manual it comes from, and a "#include" of a listing is not
    taken for a heading."""
    long_chapter = CHAPTER.replace("</body>", "<p>" + "A typemap converts a type. " * 120 + "</p></body>")
    rows = markdown_document(chapter_markdown(long_chapter, "4.4", URL), "swig-Python.md")
    titles = [t for t, _ in rows]
    assert titles[0] == "SWIG 4.4 manual — 33 SWIG and Python"
    assert all(t.startswith("SWIG 4.4 manual — 33 SWIG and Python") for t in titles)
    assert any(t.startswith("SWIG 4.4 manual — 33 SWIG and Python › 33.2.1 Running SWIG") for t in titles)
    assert not any("example.h" in t for t in titles)


def test_the_chapters_taken_are_the_ones_a_cpp_library_wrapped_for_python_java_and_csharp_needs():
    assert {"SWIG", "SWIGPlus", "Typemaps", "Library", "Python", "Java", "CSharp"} <= set(CHAPTERS)
    assert not {"Ruby", "Go", "Extending"} & set(CHAPTERS)
