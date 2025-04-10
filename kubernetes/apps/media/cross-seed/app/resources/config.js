module.exports = {
  action: "inject",
  apiKey: '{{ .CROSS_SEED_API_KEY }}',
  delay: 30,
  duplicateCategories: false,
  flatLinking: false,
  includeNonVideos: true,
  includeSingleEpisodes: false,
  linkCategory: "cross-seed",
  linkDirs: ["/data/downloads/torrents/cross-seed", "/data/LaunchBox"],
  linkType: "hardlink",
  matchMode: "partial",
  seasonFromEpisodes: 0.8,
  outputDir: null,
  port: Number(process.env.CROSS_SEED_PORT),
  qbittorrentUrl: `https://{{ .QBITTORRENT_USERNAME }}:{{ .QBITTORRENT_PASSWORD }}@qbittorrent.darkfellanetwork.com`,
  radarr: [`https://radarr.darkfellanetwork.com/?apikey={{ .RADARR_API_KEY }}`],
  skipRecheck: true,
  sonarr: [`https://sonarr.darkfellanetwork.com/?apikey={{ .SONARR_API_KEY }}`],
  useClientTorrents: true,
  torznab: [
    3, // IPT
    1, // SA
    2, // TL
  ].map(i => `https://prowlarr.darkfellanetwork.com/${i}/api?apikey={{ .PROWLARR_API_KEY }}`),
};
