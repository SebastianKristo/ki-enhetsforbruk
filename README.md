# KI Enhetsforbruk

Custom integration for Home Assistant som regner ut strømforbruk og
strømkostnad per enhet – både med **spotpris** og **Norgespris** – for i dag
og denne måneden. Alt settes opp og redigeres i brukergrensesnittet.

## Funksjoner

- Legg til, rediger og slett enheter fra integrasjonssiden
- Legg til mange enheter på en gang (flervalg av energisensorer)
- Per enhet: energi i dag / denne måneden, kostnad i dag / denne måneden
  med spotpris og med Norgespris
- Forrige periode (i går / forrige måned) som attributt
- Riktig kostnad med 15-minutters priser og negative priser
- Tåler omstart: verdier lagres, og forbruk mens HA var nede tas med
- Wh/MWh-sensorer og priser i øre/kWh konverteres automatisk
- Handlingen `ki_enhetsforbruk.calibrate` for å rette opp en verdi manuelt
- Sensorene har `state_class: total` og `last_reset`, så de fungerer i
  statistikk og energidashbordet

## Installasjon (HACS)

1. HACS → ⋮ → **Egendefinerte repositorier**
2. Lim inn URL-en til dette repoet, velg kategori **Integrasjon**
3. Installer **KI Enhetsforbruk** og start Home Assistant på nytt
4. **Innstillinger → Enheter og tjenester → Legg til integrasjon →
   KI Enhetsforbruk**

## Oppsett

Ved første oppsett velger du:

- **Spotpris-sensor** – gjeldende totalpris i kr/kWh
- **Norgespris-sensor** (valgfri) – la stå tom hvis du ikke vil ha
  Norgespris-sensorer
- **Energisensorer** (valgfritt) – hver valgt sensor blir en enhet

Etterpå, på integrasjonssiden:

| Hva | Hvor |
|---|---|
| Legg til én enhet | **Legg til enhet** |
| Endre navn eller energisensor | ⋮ ved enheten → **Rediger enhet** |
| Slette en enhet | ⋮ ved enheten → **Slett** |
| Endre prissensorer / legge til mange | **Konfigurer** |

## Slik regnes kostnaden

Hver gang energisensoren oppdateres, regnes økningen i kWh siden forrige
avlesning ut og ganges med prisen som gjelder akkurat da. Summen nullstilles
ved midnatt (dag) og ved månedsskifte (måned).

- Fall i energisensoren på mer enn 10 % tolkes som at måleren er nullstilt.
  Mindre fall regnes som støy og ignoreres.
- Er prissensoren utilgjengelig, brukes siste kjente pris.

## Rette opp en feil verdi

```yaml
action: ki_enhetsforbruk.calibrate
target:
  entity_id: sensor.kaffetrakter_energy_today
data:
  value: 0.42
```

## Lisens

MIT
