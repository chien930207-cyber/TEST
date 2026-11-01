# Validation / v6 GitHub Pages edition

## Passed in this build

- 12 Python unit tests for source validation, dimension preservation, safe SVGs, front/back candidate rules, caching, partial success, and the 136-team roster.
- 24 in-memory browser checks with clearly labelled synthetic test images. Tested 100 random rounds with 10 unique teams; complete-pair filtering; fewer-than-10 behavior; question/reveal; optional scoring; previous/next; the same round across game and exports; mobile overflow and primary touch target; and the empty state.
- Both PowerPoint outputs generated from real application code using fixture images: native animation edition (12 slides for 10 questions) and paired edition (22 slides).
- Both outputs contain SVG media, retain a 3200 x 4000 JPEG without reducing its dimensions, and contain no externally linked slide images. The native output contains click animation XML.
- Both fixture PPTX files rendered successfully; the automated slide overflow check passed for both. Representative answer slides were visually inspected.
- The exported single-file HTML ran from in-memory document content without fetching network images. The selected round, including the all-questions option, was retained.
- Desktop and 390 px mobile layouts inspected. Fixture images are NOT included in the released site or archive.

## Boundaries: not claimed as tested

- This environment blocks browser navigation and cannot retrieve external original image bytes. Browser checks above used in-memory documents, not live HTTP navigation. This is not an end-to-end GitHub Pages test.
- GitHub Actions has not been executed in the user's account, and no repository or live site has been published on the user's behalf.
- Actual success rates for the 136 logos and 136 jerseys are unknown until the GitHub build runs. The initial data/assets.json is intentionally empty, not a disguised completed image library.
- Automated jersey matching does not equal a new visual review of every jersey. The report includes candidate/review status.
- No claim is made that every source is the latest season or the highest-resolution image anywhere on the internet.
- PowerPoint XML and rendered layouts were checked; Microsoft PowerPoint desktop animation playback was not available for a physical end-user test.

## Reproduce collector tests

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_*.py' -v
```

The functional browser checks used Playwright/Chromium, SVG/PNG/JPEG fixtures and in-memory download capture. Download UI permissions, service-worker installation and real HTTP integration remain deployment-time checks. See README.md for publishing steps and the downloadable build report.
