# Ruoli della chiave di rilascio di Clonaut, letti da scripts/verify-tag.sh.
# Unico punto in cui le impronte sono scritte (e nei README, per chi verifica).
# Stesso modello di Plico: la primaria [C] resta sulla macchina del maintainer,
# certifica le sottochiavi ed è l'impronta di validpgpkeys nel PKGBUILD; non
# firma nulla. Gli allegati delle release non sono firmati: hanno SHA256SUMS.
RELEASE_PRIMARY="${CLONAUT_RELEASE_PRIMARY:-9F54724ACD0995BEC321BD30E6C5DCC0D49CCC6B}"
# Sottochiavi che possono firmare i TAG: solo quelle del maintainer. Più di
# una, separate da spazi, solo durante una rotazione.
TAG_SIGNING_SUBKEYS="${CLONAUT_TAG_SIGNING_SUBKEYS:-CEACC8CA966C2A16B7E807DB5B8D6236E7728ED4}"
