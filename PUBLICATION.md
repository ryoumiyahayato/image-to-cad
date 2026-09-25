# Code-only publication snapshot

Source commit: d405e77e7da4f8f4c871bb9abe12ff925ce36c59.

This branch contains a sanitized code-only snapshot based on the public repository's current main. The local development branch history was not imported. Private source documents, scans, drawings, review datasets, derived crops, screenshots, and generated runtime artifacts are intentionally excluded.

## Using your own input files

Open a file from its local location in the application, or pass your own image path to headless mode with --input. For example:

    python main.py --headless --input C:\path\to\your-image.png

The application writes generated files under output/ by default; that path is ignored by Git.

## Test and validation limits

The snapshot retains synthetic/unit test code and generic fixture schemas. Tests tied to the private real-document regression collection, source-specific QA cases, review exports, or internal corpus data are not included. Real-document accuracy and release qualification are unavailable without fixtures that you own or are authorized to redistribute. Private fixtures were not replaced with synthetic data presented as real benchmarks.

The current CI, FreeCAD, Windows-build, and release workflows were omitted because they consume private/source-specific inputs or upload generated evidence. A sanitized public workflow can be added after its fixture policy is established.

## License notices

The pinned source has no project-level LICENSE file, so this snapshot adds no application license claim. Existing third-party font metadata and notices are retained with the licensed font resources.
