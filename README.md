# Gawor Agro — Radar PRO Web

Jedna aplikacja webowa: logowanie Supabase Auth, dashboard, centralne leady PostgreSQL, dodawanie/edycja leadów oraz moduł OLX OAuth.

## 1. Supabase
Projekt: `aohywvqmjychkjqejfbg`
Wykonaj `supabase_rls.sql` w SQL Editor. RLS jest wymagany dla tabel publicznych używanych z przeglądarki.

W `app/index.html` jest już ustawiony publishable key projektu. Nigdy nie wkładaj tutaj `sb_secret` ani `service_role`.

## 2. Render
W Render utwórz Web Service z repozytorium. Można użyć dołączonego `render.yaml`.

Zmienne serwera:
- SUPABASE_URL=https://aohywvqmjychkjqejfbg.supabase.co
- SUPABASE_SECRET_KEY=<sekret Supabase tylko na backendzie>
- OLX_CLIENT_ID=<z OLX Developer Portal>
- OLX_CLIENT_SECRET=<z OLX Developer Portal>
- OLX_CALLBACK_URL=https://radar.gaworagro.pl/auth/olx/callback
- OLX_SCOPE=read write v2

## 3. Supabase Auth
Włącz Email/Password. Ustaw Site URL na:
`https://radar.gaworagro.pl`
oraz Redirect URL:
`https://radar.gaworagro.pl`

## 4. OLX
W OLX Developer Portal ustaw Redirect/Callback URL:
`https://radar.gaworagro.pl/auth/olx/callback`

Po wdrożeniu:
`https://radar.gaworagro.pl`
-> Zaloguj
-> OLX -> Połącz z OLX

Moduł OLX synchronizuje własne ogłoszenia autoryzowanego konta. Nie wyszukuje ogłoszeń innych użytkowników.
