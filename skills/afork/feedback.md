- Target: the afork/tfork launcher exit 127 in a fresh pane
- Requested change: On afork/tfork launcher exit 127, retry the identical command once before diagnosing, and close or retitle the dead pane (or address by surface ref) to avoid p2p ambiguity.
- Reason: on afork/tfork launcher exit 127, retry the identical command once before diagnosing; close or retitle the dead pane (or address by surface ref) to avoid p2p ambiguity
- Source: first tfork of an afork-generated claude launch.sh exited 127 (claude not found on PATH) though /opt/homebrew/bin/claude exists; immediate verbatim retry succeeded; the dead pane retained the tab title, causing a title collision warning this session's tfork results (surface:195 exit 127, surface:196 verified success with the identical command); packet provenance: producer-run.md:2436, source-local id 3

