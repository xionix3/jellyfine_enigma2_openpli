# Changelog

## [1.5.0] - 2026-11-22

- **Faster pictures**: what is on screen is downloaded before any prefetch (prefetch uses at most 2 of now 6 download threads, 3 decoders), the pictures of a screen appear together instead of one by one, and the backdrop of a newly opened screen loads at once instead of after a pause. With 300 ms per picture from the server, the start screen is complete after 0.4 s instead of 1.8 s
- **Skip intro**: during an intro, recap, preview or commercial an overlay offers "Skip intro" - OK jumps to its end, EXIT hides it; or skip automatically (setting *Skip intro/recap*). Uses Jellyfin 10.10+ media segments, on older servers the Intro Skipper plugin endpoint
- **Next episode countdown**: in the credits (Outro segment, otherwise the last 10 s) the next episode counts down from 10 - OK plays it now, EXIT cancels and the player closes at the end instead of playing on
- **Details page**: poster on the left, the facts (year, runtime, age rating, ★ rating, critics) and the personal state (resume position, ends at, watched, favourite) on separate lines instead of one overflowing line
- **Settings in groups**: General, Playback, Quality, System

## [1.4.0] - 2026-11-20

- **English and Dutch**: the whole interface (screens, menus, messages, settings, badges, plugin description) is translated. The new setting *Sprache / Language / Taal* (first in the settings) follows the menu language of the box by default - German, English or Dutch, English for every other language - or is set by hand; the change applies at once
- The default lists (*New movies*, *New episodes of my shows* ...) are shown in the chosen language, lists you named yourself keep their name
- Counts with proper singular/plural (*1 season*, *3 seasons*), decimal point in English
- Translations live in `locale/en.po` and `locale/nl.po` (Poedit); CI checks that every text is translated
- Screenshots in the README for each language

## [1.3.2] - 2026-11-20

- New name: the project lives at [xionix3/jellyfine_enigma2_openpli](https://github.com/xionix3/jellyfine_enigma2_openpli), the package is now `enigma2-plugin-extensions-jellyfine-enigma2-openpli` (opkg allows no underscores in package names) and the plugin folder `Extensions/JellyfinOpenPLi`
- The new package replaces `enigma2-plugin-extensions-jellyfine2` on install (Replaces/Conflicts), leftovers of the old folder are removed; settings, server login and lists are kept
- Releases carry the package under the new and the old stable name, so the auto-update of 1.2.x/1.3.x and old install commands keep working

## [1.3.1] - 2026-11-18

- Security: access tokens and passwords no longer appear in the plugin's log lines or error messages (the play line printed the `ApiKey` of transcoded streams - users post these lines in bug reports)
- Bug report template warns to remove tokens from logs (Enigma2/GStreamer log the stream address themselves)
- `SECURITY.md` with private vulnerability reporting; Dependabot keeps the CI actions up to date

## [1.3.0] - 2026-11-18

- **Movies, shows and every library look like the start screen**: rows for continue watching, recently added, new releases, best rated unwatched, favourites, every genre (or every folder) and A-Z; up/down jumps through them instead of a sub menu. Red shows all titles of a row as a grid
- **Search finds exact matches only**: every category (movies, shows, episodes, collections, music, people) is searched on its own, plus titles starting with the term; results that do not contain the term are dropped. Results are shown as one row per category
- Fix: shows were missing in search results - a single query for all types was filled up with fuzzy movie hits of the server before any show appeared
- **No more stutter**: pictures are decoded in ePicLoad threads instead of the GUI thread, at the exact widget size (no scaling while painting), and kept in memory; moving inside the visible cards only moves the frame, unchanged cards are not repainted, nothing is hidden and shown again while a picture loads
- **Details page**: the picture stays visible on the right, the description has room to be read completely, the cast row with photos only appears with the down key (pills and technical line make room for it); the backdrop is there at once when coming from a card
- Sidebar in every row screen; sub screens hand the sidebar back to the start screen (flat screen stack)
- Skin pictures exist pixel exact for 1080p and 720p

## [1.2.0] - 2026-11-18

- **Modern start screen**: large backdrop with title, info and buttons of the focused item, rows of 16:9 cards (one row per section), sidebar with search, movies, shows, lists and settings. The classic layout stays available (setting *Startseite* or MENU)
- **Glass look**: rounded translucent panels, selection frames, buttons and badges as alpha PNGs
- **Details page** redesigned: backdrop, action buttons, **cast row with actor photos** (OK lists the person's titles), full cast as poster grid
- **Search**: results in relevance order (exact title matches first) - an alphabetical sort used to push exact hits like "Bluey" behind the result limit; results that do not contain the term go to the end. New **categories** (movies, shows, episodes, collections, music, people) with counts; people search
- **Category filter** for mixed lists (favourites, collections, own lists, similar titles, continue watching)
- **Auto-update**: checks the GitHub releases on start (at most every 12 h), downloads the package, verifies `SHA256SUMS`, installs with opkg and offers a GUI restart; manual check via MENU, can be turned off
- **Releases are created by CI** when `CLIENT_VERSION` is bumped on `main`
- Fix: backdrops were not visible on the box in 1.0/1.1 - Enigma2 does not blend translucent label fills, the dark overlay replaced the picture. Overlays are now alpha PNGs
- Credits: "von xionix" in the plugin list, settings, about dialog and package

## [1.1.1] - 2026-11-18

- Fix: closing the list editor without saving could crash the plugin
- Fix: values in the selected row of settings/list screens were invisible (accent text on accent background)
- Fix: grouped "new episodes" tiles no longer show a misleading progress bar; the "gesehen" badge in episode lists is fully visible
- List editor: blue key renames the list
- README in German (default), English and Dutch with screenshots of the real screens; stable asset name for the one-line install

## [1.1.0] - 2026-11-18

- **My lists** ("Meine Listen"): user defined filter rules shown on the start screen (type, library, added vs. released, time window, unplayed, shows I watch, group per show, minimum rating, genre, sort, limit). Defaults: *Neue Filme*, *Neue Episoden meiner Serien*, *Serien mit neuen Folgen*, *Neu erschienen*
- **NEW** badge on posters and episode lists (configurable window)
- Backdrop of the selected title behind grid and start screen (can be disabled)
- Faster: HTTP keep-alive connection reuse, all start screen previews load in parallel and stay cached between plugin starts, next grid page posters are prefetched, optional poster cache on HDD/USB
- List item heights now always match the skin
- Requests only valid `ItemFields`

## [1.0.0] - 2026-11-17

- First release: login (password, Quick Connect, LAN discovery), start screen, poster grid with sort/filter/genre, details, seasons/episodes, music albums, search, settings
- Playback through the Enigma2 movie player with device profile, direct play or HLS transcoding, resume, progress reporting, autoplay next episode, audio/subtitle preselection
- Jellyfin 10.8 – 10.11, OpenPLi 9.0 – 9.2, HD and FHD skins
