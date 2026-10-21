# Archway — Arch Linux TUI Installer

Instalator Arch Linux dla oficjalnego Live ISO x86_64. Python 3.11+, `curses`,
obsługa klawiaturą i rozdzielenie interfejsu, planowania oraz wykonywania poleceń.
Nie wymaga pobierania bibliotek Python przed skonfigurowaniem Wi-Fi.

**Status: wersja eksperymentalna 0.1.0 wymagająca walidacji w VM przed użyciem
na fizycznym komputerze.** Kod instalacji jest zaimplementowany, ale pełna
instalacja i ponowny rozruch z Arch ISO nie zostały jeszcze zweryfikowane.
Testy jednostkowe i test konsoli nie zastępują takiej próby. Szczegóły:
[TESTING.md](TESTING.md), [ograniczenia](#ograniczenia).

## Uruchomienie

Najprościej z katalogu projektu:

```sh
sh start.sh
```

Na zwykłym Linuksie możesz obejrzeć interfejs bez instalowania systemu:

```sh
sh start.sh --demo
```

Skrypt działa również podany ścieżką z innego katalogu, np.
`sh /sciezka/archway-tui-installer/start.sh --demo`. Wybiera Python 3.11+,
sprawdza terminal i `curses`, przekazuje argumenty i nie instaluje zależności.
Właściwa instalacja wymaga konta root na Arch Live ISO. Dotychczasowe
`sh scripts/run-installer.sh` uruchamia ten sam skrypt.

1. Pobierz aktualne oficjalne [Arch ISO](https://archlinux.org/download/),
   zweryfikuj jego podpis i uruchom je w trybie docelowego systemu: UEFI lub BIOS.
2. Skopiuj repozytorium na drugi pendrive przed uruchomieniem ISO. TUI pozwala
   skonfigurować sieć bez dodatkowych zależności. Jeśli masz już Ethernet:

   ```bash
   pacman -Sy --needed git
   git clone https://github.com/MubiX-byte/archway-tui-installer.git
   cd archway-tui-installer
   bash scripts/run-installer.sh
   ```

   To polecenie `pacman -Sy` dotyczy wyłącznie jednorazowego środowiska Live ISO.
   Na zainstalowanym Arch używaj pełnej aktualizacji `pacman -Syu`.

3. Jeśli nie masz sieci, skopiuj cały folder projektu z drugiego pendrive'a
   do `/root/archway-tui-installer`, przejdź do niego i uruchom ten sam skrypt.
   Python i `curses` są częścią oficjalnego ISO. Nie potrzebujesz `pip install`.
4. Z menu wybierz **Configure Network**, następnie **Install Arch Linux**.

Kod uruchamia się jako root i korzysta z narzędzi Live ISO: `pacstrap`,
`arch-chroot`, `pacman`, `genfstab`, `sfdisk`, `partprobe`, `cryptsetup`, `iwctl`,
`systemd-networkd` i narzędzi systemów plików. Brakujące narzędzia są wykrywane
przed formatowaniem; instalator nie doinstalowuje ich bez wiedzy użytkownika.

## Bezpieczna demonstracja

```bash
python main.py --demo
python main.py --demo --plan
python main.py --demo --plan --firmware BIOS
python main.py --demo --plan --json > demo-config.json
python main.py --demo --plan --config demo-config.json
```

Demo używa syntetycznego sprzętu i nie wywołuje poleceń systemowych, sieci,
formatowania ani instalacji. Windows obsługuje eksport planu bez zależności;
do interaktywnego demo w Windows potrzeba `pip install windows-curses`.
Rzeczywista instalacja jest dostępna wyłącznie w TUI na oficjalnym Live ISO.
Nie ma bezobsługowej opcji kasowania dysku z CLI. `--config` jest przeznaczone
wyłącznie do eksportu planu i nie przyjmuje haseł.

## Nawigacja i menu

Strzałki lub `j`/`k` wybierają pozycję, Tab/Shift+Tab przenoszą wybór,
Enter zatwierdza, Esc wraca/anuluje. PgUp/PgDn przewijają długie listy i logi.
W polach Ctrl+U czyści wpis, Backspace usuwa znak, hasła są maskowane.
Rozmiar terminala można zmieniać; zalecane minimum to 80×24.
Ctrl+C w interfejsie nie przerywa operacji dyskowych. Przed potwierdzeniem
możesz wrócić lub zakończyć program; po rozpoczęciu formatowania nie ma rollbacku.

Menu główne:

| Pozycja | Działanie |
|---|---|
| Install Arch Linux | Dyski, kernel, bootloader, pulpit, konta, sterowniki, pakiety, plan i instalacja |
| Configure Network | Wi-Fi, sieci ukryte, DHCP, statyczne IPv4, test HTTPS |
| Hardware Information | CPU, RAM, GPU PCI, USB, Bluetooth, zasilanie, tryb firmware i Secure Boot |
| Advanced Options | Edytor partycji, os-prober, ponowienie pakietów, sprzątanie własnych montowań |
| View Logs | Przewijane komunikaty diagnostyczne bez haseł |
| Exit | Zamknięcie interfejsu |

## Sieć

**Wi-Fi:** wybierz interfejs i sieć, rodzaj zabezpieczeń `wpa-psk` (WPA2 / tryb
przejściowy), `sae` (WPA3) lub `open`, a następnie podaj hasło. Dostępne są
ponowne skanowanie i ukryty SSID. `iwctl` negocjuje połączenie przez `iwd`;
obsługa WPA3 zależy od sprzętu i iwd. Agent haseł otrzymuje dane przez prywatny
PTY, a nie argument procesu. 802.1X wymaga samodzielnej konfiguracji iwd.

**Ethernet:** DHCP albo adres IPv4 z prefiksem, brama i DNS. Instalator tworzy
tymczasową konfigurację `systemd-networkd` w `/run/systemd/network`.
Nie obsługuje VLAN, mostów, bondingu ani ręcznej konfiguracji IPv6.

Test internetu sprawdza HTTPS do repozytorium Arch. Sam ping nie wystarcza.
Przed pobieraniem pakietów wymagane są internet i zsynchronizowany czas.
Wybrane połączenie jest odtwarzane jako profil NetworkManager z prawami 0600
w systemie docelowym. Hasło Wi-Fi jest niezbędne w tym profilu, ale nie trafia
do logów ani publicznego planu. Istniejące połączenie skonfigurowane poza TUI
nie jest kopiowane; w takim przypadku docelowo dostępny jest przewodowy DHCP.

## Instalacja krok po kroku

1. **Dysk:** sprawdź model, pojemność, numer seryjny i aktualne partycje.
   Zamontowane nośniki, aktywny swap, aktywne mapowania/RAID i urządzenia
   Live ISO są blokowane. Nie odmontowuj nośnika Live, żeby obejść zabezpieczenie.
2. **Partycje:** wybierz tryb automatyczny albo istniejące partycje ręcznie.
   Dla nowego układu automatyczny tryb usuwa cały dysk. Ręczny tryb nie zmienia
   tablicy partycji; tworzenie/usuwanie jest dostępne w jawnym edytorze cfdisk.
3. **Filesystem:** ext4, Btrfs lub XFS. UEFI używa osobnej partycji FAT32 `/boot`.
   BIOS używa osobnego ext4 `/boot`. Root jest zawsze formatowany.
4. **Kernel:** `linux`, `linux-lts`, `linux-zen`, `linux-hardened`.
5. **Bootloader:** systemd-boot dla UEFI; GRUB dla UEFI/BIOS.
6. **Pulpit:** wybierz środowisko albo `none` do systemu konsolowego.
7. **Konta:** ustaw hostname, nazwę użytkownika i hasło; opcjonalnie root.
   Puste hasło root oznacza blokadę konta. Wymagane jest sudo lub hasło root.
8. **System:** domyślnie `pl_PL.UTF-8`, `pl`, `Europe/Warsaw`. Każdą wartość
   można zmienić. Wybierz NTP, Bluetooth, ZRAM i dodatkowe oprogramowanie.
9. **DRY RUN:** przeczytaj cały plan. `FORMAT / DATA LOSS` jest destrukcyjne.
10. **Start:** wpisz dokładnie `ERASE /dev/wybrany-dysk` (automatycznie) albo
    `FORMAT /dev/wybrany-dysk` (ręcznie). Nazwa pochodzi z wykrytego dysku.
    To przykładowy wzorzec — nie wpisuj dosłownie fikcyjnej ścieżki.
11. Instalator sprawdza konfigurację, aktualne repozytoria i ponownie tożsamość
    dysku, a dopiero potem rozpoczyna zmiany. Postęp liczy ukończone etapy.
12. Po weryfikacji plików rozruchowych, pakietów, kont i usług następuje sync
    oraz odmontowanie wyłącznie zasobów tej instalacji. Restart jest osobnym
    wyborem. Wyjmij ISO i sprawdź rozruch oraz logowanie.

## Partycjonowanie, Windows i szyfrowanie

Automatyczny tryb używa GPT w obu trybach firmware. BIOS otrzymuje partycję
BIOS boot 1 MiB i GRUB i386-pc; UEFI otrzymuje ESP 1 GiB. Ręczny BIOS obsługuje
również istniejący MBR; BIOS/GPT wymaga istniejącej partycji BIOS boot.
Root potrzebuje co najmniej 20 GiB w trybie ręcznym. Automatyczny tryb wymaga
24 GiB na root/boot plus osobno zadeklarowane home/swap.

Osobne `/home` i swap dyskowy są opcjonalne. Btrfs tworzy `@`, `@home` (jeśli
brak osobnego home), `@snapshots`, włącza kompresję zstd i opcjonalnie harmonogram
Snapper. Snapshoty są lokalne; nie stanowią kopii zapasowej ani bootowalnych
wpisów odzyskiwania. ZRAM jest domyślnie włączony; hibernacja nie jest konfigurowana.

**Obok Windows:** przygotuj wolne miejsce samodzielnie, uruchom cfdisk i utwórz
nowe partycje Linux. Wybierz tryb ręczny, nowy root i istniejącą lub nową ESP.
Przy istniejącej ESP wybierz **No** przy pytaniu o formatowanie. Instalator
wymaga ESP co najmniej 1 GiB, więc typowa mała Windows ESP może wymagać osobnej
nowej ESP. Pliki Windows nie są usuwane, lecz instalacja bootloadera zapisuje
pliki Archway i może zmienić domyślny wpis rozruchowy. Automatyczny tryb zawsze
kasuje cały wybrany dysk i nie służy do dual boot.

Instalator nie kurczy NTFS, nie odblokowuje BitLockera i nie interpretuje
niejednoznacznych etykiet jako gwarancji rozpoznania systemu operacyjnego.
NTFS/BitLocker, etykiety i typy partycji są pokazane do oceny użytkownika.
Opcjonalny `os-prober` jest wyłączony domyślnie i służy wyłącznie GRUB.

**LUKS2:** dostępny w automatycznym układzie z zaszyfrowanym root. `/boot`
pozostaje jawny. Osobny niezaszyfrowany home i swap dyskowy są wtedy zabronione;
można korzystać z ZRAM. Initramfs używa `sd-encrypt`, a wpis rozruchowy UUID
kontenera LUKS. Nie jest to szyfrowanie każdego sektora dysku.

**Secure Boot:** wykrywany, nigdy automatycznie zmieniany. Włączony albo
niemożliwy do odczytania stan blokuje instalację; ta wersja nie tworzy
podpisanego łańcucha rozruchowego i nie zarządza kluczami firmware.

## Sprzęt, sterowniki i pulpity

Intel/AMD otrzymują odpowiedni microcode. `linux-firmware` dostarcza aktualny
zestaw firmware z oficjalnych repozytoriów; standardowe moduły ładuje kernel.
Nie ma automatycznej instalacji zewnętrznych/AUR modułów Broadcom/Realtek.
Nieobsługiwany przez ISO adapter może wymagać Ethernetu lub USB tetheringu.

AMD/Intel używają Mesa i właściwego Vulkan ICD. Dla NVIDIA **auto** wybiera
konserwatywnie Nouveau: nie zgaduje generacji z marketingowej nazwy i nie
instaluje współczesnego modułu na starszej karcie. Ręczny `nvidia-open` wymaga
kodu TUxxx/GAxxx/ADxxx/GBxxx w wyniku PCI. Używa DKMS i nagłówków wybranego
kernela; instalator sprawdza powstanie modułu. Nieznane kody są odrzucane.
Starsze generacje nie dostają automatycznie sterowników legacy z AUR.
Nouveau ma ograniczenia wydajności i obsługi Wayland. Wybranie `mesa` pozostawia
wybór modułów kernelowi; nie jest metodą wyłączenia fizycznej karty.

| Pulpit | Sesja po instalacji |
|---|---|
| KDE Plasma | SDDM, Konsole, Dolphin, portal KDE |
| GNOME | GDM, terminal, Nautilus, portal GNOME |
| XFCE | LightDM + GTK greeter, Xorg, portal GTK |
| Cinnamon | LightDM + GTK greeter, Nemo, terminal, Xorg |
| Hyprland | Logowanie na TTY i polecenie `Hyprland`; Waybar, foot, fuzzel, mako, swaybg, nm-applet, portal |
| i3 | LightDM + GTK greeter, Xorg, xterm, dmenu, i3status |
| none | Konsola; NetworkManager i PipeWire nadal są instalowane |

Hyprland: SUPER+Enter uruchamia terminal, SUPER+D launcher, SUPER+Q zamyka okno,
SUPER+Shift+E kończy sesję. Konfiguracja jest podstawowa; obsługa GPU i
mapowanie nietypowych układów klawiatury mogą wymagać korekty. Wsparcie
Bluetooth audio zapewniają BlueZ, PipeWire i WirePlumber. Parowanie urządzeń
wykonuje się po instalacji. Steam włącza oficjalne multilib i odpowiednie
32-bitowe biblioteki graficzne. Proton jest wybierany w kliencie Steam.
OpenSSH jest pakietem opcjonalnym; jego usługa nie jest automatycznie włączana.

Każdy wybrany pakiet/grupa jest sprawdzany w bieżących bazach repozytoriów,
a rozwiązywanie zależności jest sprawdzane przed formatowaniem. Rolling release
może zmienić nazwy lub zgodność; wtedy instalacja zatrzymuje się z błędem.

## Diagnostyka i ponawianie

Log Live: `/var/log/archway-live.log`; po udanej konfiguracji kopia i publiczny
plan trafiają do `/var/log/archway-install.log` oraz `archway-plan.json` w systemie
docelowym. Log zawiera wyjście zakończonych poleceń, nie strumień każdego bajtu
z pacstrap. Długie polecenie może przez pewien czas nie dopisywać nowych linii.

| Objaw | Działanie |
|---|---|
| Brak Wi-Fi | Sprawdź adapter/firmware/rfkill w drugim VT; użyj Ethernetu/tetheringu |
| Złe hasło | Ponów połączenie lub przeskanuj sieci ponownie |
| HTTPS nie działa | Sprawdź DHCP, DNS, captive portal i czas systemowy |
| NTP nie synchronizuje | Udostępnij NTP; program zatrzymuje się przed kasowaniem |
| Dysk chroniony | Upewnij się, że to docelowy dysk; odmontuj jego partycje i wyłącz jego swap poza TUI |
| `/mnt` zajęte | Użyj sprzątania zasobów tej sesji lub sprawdź obce montowania samodzielnie |
| Pakiet niedostępny | Popraw wybór/aktualizuj instalator; nie podmieniaj losowo nazw |
| Pobieranie przerwane | Przy istniejącym docelowym pacmanie użyj Advanced Options → Retry package download |
| Błąd bootloadera/DKMS | Nie restartuj w ciemno; sprawdź `/mnt/boot`, logi i budowę modułu w chroot |

Ponawianie pakietów jest bezpieczne dla tablicy partycji, ale nie wznawia
całej instalacji. Jeśli pacstrap nie zdołał jeszcze zainstalować pacmana,
ta opcja zakończy się czytelnym błędem. Dalszą naprawę wykonaj z drugiego VT
lub rozpocznij nową, od początku przejrzaną instalację po sprzątnięciu montowań.
Nie ma automatycznego ponowienia formatowania ani obietnicy rollbacku.

## Testowanie i architektura

```bash
python -m unittest discover -s tests -v
python scripts/verify-repos.py
python scripts/tui-smoke.py  # Linux, prywatny PTY
python scripts/storage-smoke.py  # Linux + sfdisk, wyłącznie nowe obrazy plikowe
bash scripts/qemu-test.sh /sciezka/archlinux.iso uefi
bash scripts/qemu-test.sh /sciezka/archlinux.iso bios
```

Skrypt VM tworzy nowy plik QCOW2 i nigdy nie podłącza fizycznego dysku hosta.
Szczegółowa macierz i kryteria akceptacji: [TESTING.md](TESTING.md).
Opis przepływu i granic bezpieczeństwa: [ARCHITECTURE.md](ARCHITECTURE.md).

## Ograniczenia

- Brak zakończonego testu pełnej instalacji/reboot z ISO oraz testów na sprzęcie.
  Nie należy traktować tej wersji jako certyfikowanej do instalacji produkcyjnych.
- Tylko x86_64 i oficjalne Arch Live ISO; brak ARM, RAID, LVM, multipath i instalacji
  do aktywnego systemu hosta. Dyski z aktywnymi mapowaniami są odrzucane.
- Root musi być świeżo formatowany. Brak migracji istniejącego root i ręcznego LUKS.
- Brak automatycznego zmniejszania partycji, zarządzania Secure Boot i hibernacji.
- NVIDIA jest obsługiwana zachowawczo; zgodność konkretnego sprzętu, kernela i
  sesji graficznej wymaga osobnego testu. Brak AUR i automatycznych sterowników legacy.
- Logi mogą zawierać identyfikatory dysków, SSID i adresy sieciowe; przejrzyj je
  przed udostępnieniem. Hasła nie są logowane. Sekrety pozostają przez czas sesji
  w pamięci Pythona, której nie da się niezawodnie wyzerować.

## Źródła techniczne

- [Arch Installation guide](https://wiki.archlinux.org/title/Installation_guide)
- [Partitioning](https://wiki.archlinux.org/title/Partitioning)
- [systemd-boot](https://wiki.archlinux.org/title/Systemd-boot)
- [GRUB](https://wiki.archlinux.org/title/GRUB)
- [dm-crypt: cały system](https://wiki.archlinux.org/title/Dm-crypt/Encrypting_an_entire_system)
- [NVIDIA — tabela generacji](https://wiki.archlinux.org/title/NVIDIA)
- [Nouveau](https://wiki.archlinux.org/title/Nouveau)
- [iwctl(1)](https://man.archlinux.org/man/iwctl.1.en)
- [mkinitcpio(8)](https://man.archlinux.org/man/mkinitcpio.8)
- [NetworkManager keyfile](https://networkmanager.dev/docs/api/latest/nm-settings-keyfile.html)

Projekt nie jest oficjalnym instalatorem Arch Linux ani częścią projektu Arch.
Licencja MIT.
