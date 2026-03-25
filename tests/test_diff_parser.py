import unittest

from pr_review_bot.diff_parser import build_changed_line_map, build_review_chunks, parse_unified_diff


SAMPLE_DIFF = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,5 +1,6 @@
 import os
-VALUE = 1
+VALUE = 2
+DEBUG = True
 
 def run():
     return VALUE
@@ -10,2 +11,3 @@ def run():
     return VALUE
+    return DEBUG
"""


class DiffParserTests(unittest.TestCase):
    def test_parse_unified_diff_tracks_added_lines(self) -> None:
        patches = parse_unified_diff(SAMPLE_DIFF)
        self.assertEqual(len(patches), 1)
        patch = patches[0]
        self.assertEqual(patch.path, "src/app.py")
        self.assertEqual(patch.added_lines, {2, 3, 12})

    def test_build_review_chunks_renders_head_line_markers(self) -> None:
        patches = parse_unified_diff(SAMPLE_DIFF)
        chunks, omitted = build_review_chunks(patches, max_chunk_chars=600, max_chunks=4)
        self.assertEqual(omitted, 0)
        self.assertEqual(len(chunks), 1)
        self.assertIn("R     2 | +VALUE = 2", chunks[0].text)
        self.assertIn("L     2 | -VALUE = 1", chunks[0].text)

    def test_build_changed_line_map_groups_lines_by_file(self) -> None:
        patches = parse_unified_diff(SAMPLE_DIFF)
        changed = build_changed_line_map(patches)
        self.assertEqual(changed, {"src/app.py": {2, 3, 12}})

if __name__ == "__main__":
    unittest.main()
