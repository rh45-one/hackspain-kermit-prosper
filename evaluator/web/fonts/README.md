# Fuentes locales de la consola

`inter-latin*.woff2` e `inter-tight-latin*.woff2` son **Inter** e **Inter
Tight** (proyecto Inter: https://github.com/rsms/inter), licencia SIL Open
Font License 1.1 — el texto completo está en `OFL.txt`.

Son fuentes variables (`wght 100–900`): un solo archivo por familia y subset
cubre 400, 500 y 600, que es todo lo que la consola usa.

Se sirven desde el propio evaluador (`/static/fonts/…`) a propósito: la
consola tiene que funcionar en la wifi del venue, sin CDN y sin build. Si
estos archivos no estuvieran, `styles.css` cae al stack del sistema
(`system-ui`) y la página sigue siendo legible.
