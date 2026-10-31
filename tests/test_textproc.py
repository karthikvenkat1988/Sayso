from sayso.core import textproc as tp


def test_fillers_removed_but_not_inside_words():
    assert tp.remove_fillers("um I think uh we should go") == "I think we should go"
    assert "umbrella" in tp.remove_fillers("bring the umbrella")
    assert tp.remove_fillers("hmm, okay") == "okay"


def test_repeats_collapsed():
    assert tp.remove_fillers("we we should should go") == "we should go"


def test_scratch_that():
    assert tp.apply_scratch_that("send it Monday scratch that Tuesday") == "Tuesday"
    assert tp.apply_scratch_that("Hello there. Bad part, delete that. Good part") == "Hello there. Good part"


def test_spoken_punctuation():
    assert tp.apply_spoken_punctuation("hello comma world period") == "hello, world."
    assert tp.apply_spoken_punctuation("first new line second") == "first\nsecond"
    assert tp.apply_spoken_punctuation("a comma new line b") == "a,\nb"
    assert tp.apply_spoken_punctuation("one new paragraph two") == "one\n\ntwo"
    assert tp.apply_spoken_punctuation("really question mark") == "really?"


def test_vocabulary_whole_word_case_insensitive():
    vocab = {"sayso": "Sayso", "k8s": "Kubernetes"}
    assert tp.apply_vocabulary("use SAYSO with k8s now", vocab) == "use Sayso with Kubernetes now"
    assert tp.apply_vocabulary("sayson", vocab) == "sayson"
    assert tp.apply_vocabulary("x", {}) == "x"


def test_vocabulary_longest_first_and_backslash():
    assert tp.apply_vocabulary("a b c", {"a": "1", "a b": "2"}) == "2 c"
    assert tp.apply_vocabulary("path", {"path": "C:\\tmp"}) == "C:\\tmp"


def test_capitalize_and_terminal_punctuation():
    assert tp.capitalize_sentences("hello. i am here! ok") == "Hello. I am here! Ok"
    assert tp.ensure_terminal_punctuation("hello") == "hello."
    assert tp.ensure_terminal_punctuation("hello?") == "hello?"
    assert tp.ensure_terminal_punctuation("") == ""


def test_basic_cleanup():
    assert tp.basic_cleanup("um hello comma i am here") == "Hello, I am here"


def test_snippets():
    snips = {"my address": "1 Main St"}
    assert tp.match_snippet("My address.", snips) == "1 Main St"
    assert tp.match_snippet("insert my address", snips) == "1 Main St"
    assert tp.match_snippet("what is my address", snips) is None
    assert tp.match_snippet("x", {}) is None


def test_strip_model_wrapping():
    assert tp.strip_model_wrapping('"Hi there"') == "Hi there"
    assert tp.strip_model_wrapping("Here is the rewritten text:\nHi there") == "Hi there"
    assert tp.strip_model_wrapping("“Hi”") == "Hi"
    assert tp.strip_model_wrapping("plain") == "plain"
    # Quotes that open and close different phrases are part of the text.
    assert tp.strip_model_wrapping('"Hi" she said "ok"') == '"Hi" she said "ok"'
    assert tp.strip_model_wrapping("“Yes” and “no”") == "“Yes” and “no”"


def test_word_count():
    assert tp.word_count("a b  c") == 3
