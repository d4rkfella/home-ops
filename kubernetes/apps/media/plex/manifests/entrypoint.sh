#!/usr/bin/env bash

prefFile="${PLEX_MEDIA_SERVER_APPLICATION_SUPPORT_DIR}/Plex Media Server/Preferences.xml"

# Remove pid file
rm -f "${PLEX_MEDIA_SERVER_APPLICATION_SUPPORT_DIR}/Plex Media Server/plexmediaserver.pid"

exec \
    /usr/lib/plexmediaserver/Plex\ Media\ Server \
    "$@"
