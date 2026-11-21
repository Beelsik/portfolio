"""Localized master data (vendors, SKUs, contracts) and interactive presets for RU, UK, EN, FR."""

from __future__ import annotations

from typing import Any

from .models import CatalogItem, ContractTerms, VendorRecord


def get_master_data(lang: str = "ru") -> tuple[list[VendorRecord], list[CatalogItem], list[ContractTerms], str]:
    """Return statutory-valid vendor, catalog SKUs, active contract caps, and regime for lang."""
    l = (lang or "ru").lower()

    if l == "uk":
        vendors = [
            VendorRecord(
                vendor_id="V-UA-01",
                name="ТОВ «ЕлектроПром Постач»",
                regime="UA",
                tax_id="38492011",
                bik="322313",
                approved_bank_account="UA213223130000026007233566001",
            )
        ]
        catalog = [
            CatalogItem(
                sku="CBL-VVG-3X25",
                name="Кабель силовий ВВГнг-П 3х2,5 (Одескабель)",
                unit="m",
                list_price_minor=5600,
                aliases=["ввг 3*2.5", "ввгнг 3х2,5", "кабель 3x2.5", "одескабель 3*2.5"],
                brand="Odeskabel",
            ),
            CatalogItem(
                sku="CBL-VVG-3X15",
                name="Кабель силовий ВВГнг-П 3х1,5 (Одескабель)",
                unit="m",
                list_price_minor=3800,
                aliases=["ввг 3*1.5", "ввгнг 3х1,5", "кабель 3x1.5"],
                brand="Odeskabel",
            ),
            CatalogItem(
                sku="BRK-S201-C16",
                name="Автоматичний вимикач ABB S201 C16 1P 6kA",
                unit="pcs",
                list_price_minor=24500,
                aliases=["автомат c16", "вимикач c16", "abb s201 c16", "s201 16a"],
                brand="ABB",
            ),
            CatalogItem(
                sku="BRK-S201-C25",
                name="Автоматичний вимикач ABB S201 C25 1P 6kA",
                unit="pcs",
                list_price_minor=27500,
                aliases=["автомат c25", "вимикач c25", "abb s201 c25"],
                brand="ABB",
            ),
            CatalogItem(
                sku="PIPE-PVC-D20",
                name="Гофротруба ПВХ d20 з протяжкою",
                unit="m",
                list_price_minor=1600,
                aliases=["гофра d20", "гофротруба д20", "труба пвх 20мм"],
                brand="DKC",
            ),
            CatalogItem(
                sku="LED-PNL-36W",
                name="Світильник LED 36W 600x600 IP40",
                unit="pcs",
                list_price_minor=69000,
                aliases=["панель 36вт", "світильник 36w", "led 36w ip40"],
                brand="Philips",
            ),
        ]
        contracts = [
            ContractTerms(
                contract_number="ДП-2026/44",
                vendor_id="V-UA-01",
                currency="UAH",
                valid_from="2026-01-01",
                valid_until="2026-12-31",
                max_variance_pct=0.0,
                price_caps_minor={
                    "CBL-VVG-3X25": 5400,
                    "CBL-VVG-3X15": 3600,
                    "BRK-S201-C16": 24000,
                    "BRK-S201-C25": 27000,
                    "PIPE-PVC-D20": 1500,
                    "LED-PNL-36W": 68000,
                },
            )
        ]
        return vendors, catalog, contracts, "UA"

    if l == "en":
        vendors = [
            VendorRecord(
                vendor_id="V-UK-01",
                name="NorthGrid Electrical Supply Ltd",
                regime="EU",
                tax_id="GB849201472",
                bik="",
                approved_bank_account="GB29NWBK60161331926819",
            )
        ]
        catalog = [
            CatalogItem(
                sku="CBL-NYM-3X25",
                name="NYM-J 3x2.5mm2 Twin & Earth Power Cable",
                unit="m",
                list_price_minor=145,
                aliases=["nym 3*2.5", "cable 3x2.5", "3x2.5mm2"],
                brand="Prysmian",
            ),
            CatalogItem(
                sku="CBL-NYM-3X15",
                name="NYM-J 3x1.5mm2 Lighting Cable",
                unit="m",
                list_price_minor=98,
                aliases=["nym 3*1.5", "cable 3x1.5", "3x1.5mm2"],
                brand="Prysmian",
            ),
            CatalogItem(
                sku="MCB-B16-6KA",
                name="Schneider Acti9 iC60N C16 MCB 1P 6kA",
                unit="pcs",
                list_price_minor=920,
                aliases=["mcb c16", "breaker 16a", "acti9 c16"],
                brand="Schneider",
            ),
            CatalogItem(
                sku="MCB-C25-6KA",
                name="Schneider Acti9 iC60N C25 MCB 1P 6kA",
                unit="pcs",
                list_price_minor=1040,
                aliases=["mcb c25", "breaker 25a", "acti9 c25"],
                brand="Schneider",
            ),
            CatalogItem(
                sku="COND-PVC-20",
                name="PVC Corrugated Conduit d20 with draw wire",
                unit="m",
                list_price_minor=65,
                aliases=["conduit 20mm", "pvc d20", "flex conduit 20"],
                brand="MK",
            ),
            CatalogItem(
                sku="LUM-PNL-36W",
                name="LED Panel 36W 600x600 IP54",
                unit="pcs",
                list_price_minor=3400,
                aliases=["led 36w", "panel 36w ip54"],
                brand="Philips",
            ),
        ]
        contracts = [
            ContractTerms(
                contract_number="MSA-2026-09",
                vendor_id="V-UK-01",
                currency="GBP",
                valid_from="2026-01-01",
                valid_until="2026-12-31",
                max_variance_pct=0.0,
                price_caps_minor={
                    "CBL-NYM-3X25": 140,
                    "CBL-NYM-3X15": 95,
                    "MCB-B16-6KA": 900,
                    "MCB-C25-6KA": 1000,
                    "COND-PVC-20": 62,
                    "LUM-PNL-36W": 3250,
                },
            )
        ]
        return vendors, catalog, contracts, "EU"

    if l == "fr":
        vendors = [
            VendorRecord(
                vendor_id="V-FR-01",
                name="VoltaPro Distribution SAS",
                regime="FR",
                tax_id="73282932000074",
                bik="",
                approved_bank_account="FR1420041010050500013M02606",
            )
        ]
        catalog = [
            CatalogItem(
                sku="CBL-R2V-3G25",
                name="Câble U-1000 R2V 3G2,5mm2 Nexans",
                unit="m",
                list_price_minor=168,
                aliases=["r2v 3g2.5", "cable 3x2.5", "3*2,5"],
                brand="Nexans",
            ),
            CatalogItem(
                sku="CBL-R2V-3G15",
                name="Câble U-1000 R2V 3G1,5mm2 Nexans",
                unit="m",
                list_price_minor=112,
                aliases=["r2v 3g1.5", "cable 3x1.5", "3*1,5"],
                brand="Nexans",
            ),
            CatalogItem(
                sku="DISJ-C16-6KA",
                name="Disjoncteur Legrand DNX3 C16 1P+N 6kA",
                unit="pcs",
                list_price_minor=1150,
                aliases=["disjoncteur c16", "legrand c16", "dnx3 16a"],
                brand="Legrand",
            ),
            CatalogItem(
                sku="DISJ-C25-6KA",
                name="Disjoncteur Legrand DNX3 C25 1P+N 6kA",
                unit="pcs",
                list_price_minor=1290,
                aliases=["disjoncteur c25", "legrand c25", "dnx3 25a"],
                brand="Legrand",
            ),
            CatalogItem(
                sku="GAINE-ICTA-20",
                name="Gaine ICTA d20 avec tire-fil",
                unit="m",
                list_price_minor=75,
                aliases=["icta d20", "gaine 20mm", "tube 20"],
                brand="Courant",
            ),
            CatalogItem(
                sku="DALLE-LED-36W",
                name="Dalle LED 36W 600x600 IP54",
                unit="pcs",
                list_price_minor=4200,
                aliases=["dalle 36w", "led 36w ip54"],
                brand="Philips",
            ),
        ]
        contracts = [
            ContractTerms(
                contract_number="ACC-2026-14",
                vendor_id="V-FR-01",
                currency="EUR",
                valid_from="2026-01-01",
                valid_until="2026-12-31",
                max_variance_pct=0.0,
                price_caps_minor={
                    "CBL-R2V-3G25": 160,
                    "CBL-R2V-3G15": 108,
                    "DISJ-C16-6KA": 1120,
                    "DISJ-C25-6KA": 1240,
                    "GAINE-ICTA-20": 72,
                    "DALLE-LED-36W": 3950,
                },
            )
        ]
        return vendors, catalog, contracts, "FR"

    # Default: RU
    vendors = [
        VendorRecord(
            vendor_id="V-RU-01",
            name="ООО «СеверЭнергоСнаб»",
            regime="RU",
            tax_id="7707083893",
            bik="044525225",
            approved_bank_account="40702810438000124500",
        )
    ]
    catalog = [
        CatalogItem(
            sku="CBL-VVG-3X25",
            name="Кабель ВВГнг(А)-LS 3х2,5 ГОСТ",
            unit="m",
            list_price_minor=12200,
            aliases=["ввг 3*2.5", "ввгнг 3х2,5", "кабель 3x2.5", "ввгнг лс 3*2.5м"],
            brand="Севкабель",
        ),
        CatalogItem(
            sku="CBL-VVG-3X15",
            name="Кабель ВВГнг(А)-LS 3х1,5 ГОСТ",
            unit="m",
            list_price_minor=8500,
            aliases=["ввг 3*1.5", "ввгнг 3х1,5", "кабель 3x1.5"],
            brand="Севкабель",
        ),
        CatalogItem(
            sku="BRK-S201-C16",
            name="Автоматический выключатель ABB S201 C16 1P 6kA",
            unit="pcs",
            list_price_minor=47500,
            aliases=["автомат c16", "выключатель с16", "abb s201 c16", "автом выкл с16 1п"],
            brand="ABB",
        ),
        CatalogItem(
            sku="BRK-S201-C25",
            name="Автоматический выключатель ABB S201 C25 1P 6kA",
            unit="pcs",
            list_price_minor=51000,
            aliases=["автомат c25", "выключатель с25", "abb s201 c25"],
            brand="ABB",
        ),
        CatalogItem(
            sku="PIPE-PVC-D20",
            name="Труба гофрированная ПВХ d20 с зондом",
            unit="m",
            list_price_minor=3000,
            aliases=["гофра d20", "гофра пвх д20", "труба пвх d20"],
            brand="DKC",
        ),
        CatalogItem(
            sku="LED-PNL-36W",
            name="Светильник LED панель 36Вт 600x600 IP40",
            unit="pcs",
            list_price_minor=135000,
            aliases=["панель 36вт", "светильник 36w", "led 36w ip40"],
            brand="IEK",
        ),
    ]
    contracts = [
        ContractTerms(
            contract_number="ДП-2026/11",
            vendor_id="V-RU-01",
            currency="RUB",
            valid_from="2026-01-01",
            valid_until="2026-12-31",
            max_variance_pct=0.0,
            price_caps_minor={
                "CBL-VVG-3X25": 11800,
                "CBL-VVG-3X15": 8200,
                "BRK-S201-C16": 46000,
                "BRK-S201-C25": 49500,
                "PIPE-PVC-D20": 2900,
                "LED-PNL-36W": 132000,
            },
        )
    ]
    return vendors, catalog, contracts, "RU"


def get_presets(lang: str = "ru") -> dict[str, dict[str, Any]]:
    """Interactive presets for the web playground (one traps-packed, one clean coil/pack auto-pass)."""
    l = (lang or "ru").lower()

    if l == "uk":
        return {
            "traps": {
                "id": "traps",
                "label": "Рахунок № 184 (4 приховані пастки)",
                "text": "\n".join(
                    [
                        "Постачальник: ТОВ «ЕлектроПром Постач»",
                        "Рахунок № 184 від 2026-11-19 | Договір ДП-2026/44",
                        "ЄДРПОУ: 38492011 | IBAN: UA653223130000026009998877002",
                        "№ | Найменування | К-сть | Од. | Ціна (₴) | Сума (₴)",
                        "1 | Кабель ВВГнг-П 3х2,5 (Одескабель) | 200 | м | 60.00 | 12000.00",
                        "2 | Кабель ВВГнг-П 3х1,5 (склад Київ) | 150 | м | 36.00 | 6400.00",
                        "3 | Автомат ABB S201 C16 1P 6kA | 24 | шт | 240.00 | 5760.00",
                        "4 | Гофротруба ПВХ d20 з протяжкою (бухта 100м) | 2 | бухта | 1500.00 | 3000.00",
                        "У т.ч. ПДВ 20%: 4526.67 ₴",
                        "Разом до сплати: 27160.00 ₴",
                    ]
                ),
            },
            "clean_packs": {
                "id": "clean_packs",
                "label": "Чистий рахунок (бухти + скорочення → автопрохід)",
                "text": "\n".join(
                    [
                        "Постачальник: ТОВ «ЕлектроПром Постач»",
                        "Рахунок № 185 від 2026-11-20 | Договір ДП-2026/44",
                        "ЄДРПОУ: 38492011 | IBAN: UA213223130000026007233566001",
                        "1 | ввгнг 3*2.5м (бухта 100м) | 3 | бухта | 5300.00 | 15900.00",
                        "2 | вимикач c16 abb s201 | 20 | шт | 238.00 | 4760.00",
                        "3 | гофра д20 пвх (бухта 100м) | 1 | бухта | 1480.00 | 1480.00",
                        "У т.ч. ПДВ 20%: 3690.00 ₴",
                        "Разом до сплати: 22140.00 ₴",
                    ]
                ),
            },
        }

    if l == "en":
        return {
            "traps": {
                "id": "traps",
                "label": "Invoice #184 (4 hidden traps)",
                "text": "\n".join(
                    [
                        "Supplier: NorthGrid Electrical Supply Ltd",
                        "Invoice #INV-184 Date 2026-11-19 | Contract MSA-2026-09",
                        "VAT ID: GB849201472 | IBAN: GB65NWBK60161399887766",
                        "# | Description | Qty | Unit | Price (£) | LineTotal (£)",
                        "1 | NYM-J 3x2.5mm2 Twin & Earth Cable | 200 | m | 1.56 | 312.00",
                        "2 | NYM-J 3x1.5mm2 Lighting Cable | 150 | m | 0.95 | 172.50",
                        "3 | Schneider Acti9 iC60N C16 MCB 1P | 24 | pcs | 9.00 | 216.00",
                        "4 | PVC Conduit d20 with draw wire (coil 100m) | 2 | coil | 62.00 | 124.00",
                        "VAT (20%): £137.42",
                        "Total Due: £824.50",
                    ]
                ),
            },
            "clean_packs": {
                "id": "clean_packs",
                "label": "Clean invoice (coils + shorthand → auto-pass)",
                "text": "\n".join(
                    [
                        "Supplier: NorthGrid Electrical Supply Ltd",
                        "Invoice #INV-185 Date 2026-11-20 | Contract MSA-2026-09",
                        "VAT ID: GB849201472 | IBAN: GB29NWBK60161331926819",
                        "1 | nym 3*2.5 cable (coil 100m) | 3 | coil | 138.00 | 414.00",
                        "2 | mcb c16 acti9 1p 6ka | 20 | pcs | 8.90 | 178.00",
                        "3 | pvc conduit d20 (coil 100m) | 1 | coil | 60.00 | 60.00",
                        "VAT (20%): £108.67",
                        "Total Due: £652.00",
                    ]
                ),
            },
        }

    if l == "fr":
        return {
            "traps": {
                "id": "traps",
                "label": "Facture #184 (4 anomalies cachées)",
                "text": "\n".join(
                    [
                        "Fournisseur: VoltaPro Distribution SAS",
                        "Facture N°FAC-184 du 2026-11-19 | Contrat ACC-2026-14",
                        "SIRET: 73282932000074 | IBAN: FR1320041010050500999K88112",
                        "N° | Désignation | Qté | Unité | P.U. (€) | Total (€)",
                        "1 | Câble U-1000 R2V 3G2,5mm2 Nexans | 200 | m | 1.78 | 356.00",
                        "2 | Câble U-1000 R2V 3G1,5mm2 Nexans | 150 | m | 1.08 | 192.00",
                        "3 | Disjoncteur Legrand DNX3 C16 1P+N | 24 | pcs | 11.20 | 268.80",
                        "4 | Gaine ICTA d20 tire-fil (couronne 100m) | 2 | couronne | 72.00 | 144.00",
                        "Dont TVA 20%: 160.13 €",
                        "Montant TTC: 960.80 €",
                    ]
                ),
            },
            "clean_packs": {
                "id": "clean_packs",
                "label": "Facture conforme (couronnes → passage auto)",
                "text": "\n".join(
                    [
                        "Fournisseur: VoltaPro Distribution SAS",
                        "Facture N°FAC-185 du 2026-11-20 | Contrat ACC-2026-14",
                        "SIRET: 73282932000074 | IBAN: FR1420041010050500013M02606",
                        "1 | cable r2v 3g2.5 (couronne 100m) | 3 | couronne | 158.00 | 474.00",
                        "2 | disjoncteur c16 legrand dnx3 | 20 | pcs | 11.00 | 220.00",
                        "3 | gaine icta d20 (couronne 100m) | 1 | couronne | 70.00 | 70.00",
                        "Dont TVA 20%: 127.33 €",
                        "Montant TTC: 764.00 €",
                    ]
                ),
            },
        }

    # RU default
    return {
        "traps": {
            "id": "traps",
            "label": "Счёт № 184 (4 скрытые ловушки)",
            "text": "\n".join(
                [
                    "Поставщик: ООО «СеверЭнергоСнаб»",
                    "Счёт № 184 от 2026-11-19 | Договор ДП-2026/11",
                    "ИНН: 7707083893 | БИК: 044525225 | Р/С: 40702810638000998811",
                    "№ | Наименование | Кол-во | Ед. | Цена (₽) | Сумма (₽)",
                    "1 | Кабель ВВГнг(А)-LS 3х2,5 ГОСТ | 200 | м | 131.00 | 26200.00",
                    "2 | Кабель ВВГнг(А)-LS 3х1,5 (склад Челны) | 150 | м | 82.00 | 14300.00",
                    "3 | Автомат ABB S201 C16 1P 6kA | 24 | шт | 460.00 | 11040.00",
                    "4 | Труба гофр ПВХ d20 с зондом (бухта 100м) | 2 | бухта | 2800.00 | 5600.00",
                    "В т.ч. НДС 20%: 9523.33 ₽",
                    "Итого к оплате: 57140.00 ₽",
                ]
            ),
        },
        "clean_packs": {
            "id": "clean_packs",
            "label": "Чистый счёт (бухты + сокращения → автопроход)",
            "text": "\n".join(
                [
                    "Поставщик: ООО «СеверЭнергоСнаб»",
                    "Счёт № 185 от 2026-11-20 | Договор ДП-2026/11",
                    "ИНН: 7707083893 | БИК: 044525225 | Р/С: 40702810438000124500",
                    "1 | ввгнг лс 3*2.5м (бухта 100м) | 3 | бухта | 11500.00 | 34500.00",
                    "2 | автом выкл с16 1п 6ка | 20 | шт | 455.00 | 9100.00",
                    "3 | гофра пвх д20 с зондом (бухта 100м) | 1 | бухта | 2850.00 | 2850.00",
                    "В т.ч. НДС 20%: 7741.67 ₽",
                    "Итого к оплате: 46450.00 ₽",
                ]
            ),
        },
    }
