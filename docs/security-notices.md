# Public upstream client identifiers

GitHub secret scanning alerts 1 and 2 refer to public Google client identifiers included verbatim in YouTube.js 18.3.0 and BgUtils 4.0.3. Both values were compared with their upstream source; neither is a Riffuna account credential or a user-created Google API key.

- [YouTube.js constants](https://github.com/LuanRT/YouTube.js/blob/main/src/utils/Constants.ts)
- [BgUtils constants](https://github.com/LuanRT/BgUtils/blob/main/src/utils/constants.ts)

Third-party JavaScript is restored during the build from integrity-pinned npm packages rather than committed as generated vendor files. The APK still includes the upstream client code needed for playback, with its licenses. This does not remove or disguise a private credential: no private Google credential is used.

Android release signing uses a separate private keystore. The keystore and password must never enter Git, APK assets, logs or release attachments. GitHub Actions receives the signing material only through encrypted repository secrets and never exposes it to pull requests. Existing releases are not overwritten when a new APK is published.
