"""Public synthetic paired cases; labels authored before any candidate inference."""
import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FAMILIES = [
    ('new-expense-roles',
     ['Wessen Reisekosten kontrolliert Elisa?', 'Wer kontrolliert die Reisekosten von Elisa?'],
     ['Whose travel expenses does Elisa check?', 'Who checks Elisa’s travel expenses?'],
     ['Elisa kontrolliert die Reisekosten von Jonas.', 'Klara kontrolliert die Reisekosten von Elisa.', 'Jonas kontrolliert Klaras Arbeitszeiten.', 'Elisa erstellt nur die Reisekostenrichtlinie.', 'Klara kontrolliert Rechnungen von Lieferanten.', 'Jonas reicht eine Urlaubsplanung ein.']),
    ('new-permission-negation',
     ['Wer darf die Personalakten ausdrücklich nicht öffnen?', 'Wer darf die Personalakten ausdrücklich öffnen?'],
     ['Who is explicitly not allowed to open personnel files?', 'Who is explicitly allowed to open personnel files?'],
     ['Jonas darf die Personalakten nicht öffnen; sein Antrag wurde abgelehnt.', 'Klara darf die Personalakten öffnen; ihr Antrag wurde genehmigt.', 'Elisa darf öffentliche Stellenanzeigen öffnen.', 'Für Jonas ist der Urlaubsplan freigegeben.', 'Klaras Zugang zum Rechnungsarchiv ist gesperrt.', 'Die Personalakten werden regelmäßig archiviert.']),
    ('new-withdrawn-approval',
     ['Welcher Auftrag hat nach dem Widerruf keine gültige Freigabe mehr?', 'Welcher Auftrag besitzt weiterhin eine gültige Freigabe?'],
     ['Which order no longer has valid approval after revocation?', 'Which order still has valid approval?'],
     ['Die Freigabe für Auftrag Alpha wurde am Montag widerrufen und nicht erneut erteilt.', 'Die Freigabe für Auftrag Beta besteht unverändert fort.', 'Auftrag Gamma wartet noch auf eine erstmalige Freigabe.', 'Für Auftrag Delta wurde lediglich die Lieferadresse korrigiert.', 'Die Genehmigungsrichtlinie wird jedes Jahr geprüft.', 'Die Lieferung zu Auftrag Epsilon wurde bereits abgeschlossen.']),
    ('new-effective-date',
     ['Welche Hausordnung gilt im März des Jahres zweitausendsechsundzwanzig?', 'Welche Hausordnung gilt ab April des Jahres zweitausendsechsundzwanzig?'],
     ['Which house rules apply in March of the year twenty twenty-six?', 'Which house rules apply from April of the year twenty twenty-six?'],
     ['Die Hausordnung Fassung Rot gilt bis einschließlich März 2026.', 'Die Hausordnung Fassung Blau tritt am 1. April 2026 in Kraft und ersetzt Fassung Rot.', 'Die Hausordnung Fassung Grün wurde nur als Entwurf veröffentlicht.', 'Die Gartenordnung wird im Mai besprochen.', 'Der Wirtschaftsplan gilt für das Kalenderjahr.', 'Die Hausordnung von Nachbargebäude Ost ist unabhängig.']),
    ('new-decimal-invoice',
     ['Welche Rechnung beträgt exakt hundertacht Euro und zweiunddreißig Cent?', 'Welche Rechnung beträgt exakt hundertacht Euro und dreiundzwanzig Cent?'],
     ['Which invoice totals exactly one hundred eight euros and thirty-two cents?', 'Which invoice totals exactly one hundred eight euros and twenty-three cents?'],
     ['Rechnung Rosenweg beträgt 108,32 Euro.', 'Rechnung Tulpenweg beträgt 108,23 Euro.', 'Rechnung Nelkenweg beträgt 180,32 Euro.', 'Angebot Lilienweg beträgt 108,32 Euro und ist keine Rechnung.', 'Rechnung Auenweg beträgt 1.083,20 Euro.', 'Die Summe aller Rechnungen wird monatlich ermittelt.']),
    ('new-net-gross',
     ['Welcher Betrag ist der Bruttobetrag der Rechnung Nord?', 'Welcher Betrag ist der Nettobetrag der Rechnung Nord?'],
     ['Which amount is the gross total of invoice North?', 'Which amount is the net total of invoice North?'],
     ['Rechnung Nord: Bruttobetrag 119 Euro einschließlich Umsatzsteuer.', 'Rechnung Nord: Nettobetrag 100 Euro ohne Umsatzsteuer.', 'Rechnung Nord: Umsatzsteuerbetrag 19 Euro.', 'Rechnung Süd: Bruttobetrag 100 Euro.', 'Das Angebot West wurde noch nicht berechnet.', 'Die Rechnungsliste enthält auch Gutschriften.']),
    ('new-units',
     ['Welche Leitung hat einen Durchmesser von zwanzig Millimetern?', 'Welche Leitung hat einen Durchmesser von zwanzig Zentimetern?'],
     ['Which pipe has a diameter of twenty millimetres?', 'Which pipe has a diameter of twenty centimetres?'],
     ['Die Leitung Rot hat einen Durchmesser von 20 Millimetern.', 'Die Leitung Blau hat einen Durchmesser von 20 Zentimetern.', 'Die Leitung Grün ist 20 Meter lang; ihr Durchmesser ist unbekannt.', 'Die Leitung Gelb ist 2 Millimeter dick.', 'Die Leitung Weiß besitzt eine Isolierung.', 'Die Leitungen werden durch einen Fachbetrieb geprüft.']),
    ('new-version-rollback',
     ['Welche Version ist nach der Rücknahme aktuell produktiv?', 'Welche Version wurde wegen des Fehlers zurückgenommen?'],
     ['Which version is currently in production after the rollback?', 'Which version was rolled back because of the defect?'],
     ['Nach der Rücknahme läuft die Anwendung wieder produktiv in Version 3.2.', 'Version 3.3 wurde wegen eines Fehlers zurückgenommen und ist nicht produktiv.', 'Version 3.4 liegt nur als Testversion vor.', 'Version 3.1 ist im historischen Archiv abgelegt.', 'Das Handbuch wurde ohne Versionswechsel berichtigt.', 'Die Datenbankversion ist unabhängig von der Anwendung.']),
    ('new-near-identifiers',
     ['Welcher Vorgang gehört zum Aktenzeichen AZ-1042?', 'Welcher Vorgang gehört zum Aktenzeichen AZ-1024?'],
     ['Which case belongs to reference AZ-1042?', 'Which case belongs to reference AZ-1024?'],
     ['Aktenzeichen AZ-1042 betrifft die Fensterreparatur am Nordhaus.', 'Aktenzeichen AZ-1024 betrifft die Dachreparatur am Südhaus.', 'Aktenzeichen AZ-1402 betrifft die Heizungswartung.', 'Aktenzeichen BZ-1042 betrifft die Gartenpflege.', 'Eine allgemeine Anleitung erläutert Aktenzeichen.', 'Der Vorgang ohne Aktenzeichen ist noch nicht zugeordnet.']),
    ('new-umlaut-names',
     ['Wer betreut die Wohnung in der Müllerstraße?', 'Wer betreut die Wohnung in der Möllerstraße?'],
     ['Who manages the apartment on Müllerstraße?', 'Who manages the apartment on Möllerstraße?'],
     ['Die Wohnung in der Müllerstraße wird von Elisa betreut.', 'Die Wohnung in der Möllerstraße wird von Jonas betreut.', 'Die Wohnung in der Malerstraße wird von Klara betreut.', 'Elisa betreut zusätzlich eine Garage am Auenweg.', 'Die Straßenreinigung hat einen eigenen Zeitplan.', 'Wohnungen ohne Verwaltung werden gesondert erfasst.']),
    ('new-passive-roles',
     ['Wer wurde von Klara über die Abschaltung informiert?', 'Von wem wurde Klara über die Abschaltung informiert?'],
     ['Who was informed by Klara about the shutdown?', 'By whom was Klara informed about the shutdown?'],
     ['Jonas wurde von Klara über die Abschaltung informiert.', 'Klara wurde von Elisa über die Abschaltung informiert.', 'Elisa wurde von Jonas über den Urlaub informiert.', 'Klara hat die Abschaltung nur im Kalender vermerkt.', 'Jonas wurde über eine andere Wartung informiert.', 'Die Abschaltung ist im Betriebshandbuch beschrieben.']),
    ('new-conditional-exception',
     ['Wann darf eine Reparatur ohne vorherige Freigabe beauftragt werden?', 'Wann ist vor der Reparatur eine Freigabe erforderlich?'],
     ['When may a repair be ordered without prior approval?', 'When is approval required before a repair?'],
     ['Bei akuter Gefahr durch einen Rohrbruch darf die Notfallreparatur ohne vorherige Freigabe beauftragt werden.', 'Für planbare Schönheitsreparaturen ist vor der Beauftragung eine Freigabe erforderlich.', 'Ein Reparaturangebot allein gilt nicht als Beauftragung.', 'Die Freigabe von Urlaubsanträgen folgt einer anderen Richtlinie.', 'Regelmäßige Kontrollen sollen Rohrbrüche vermeiden.', 'Eine abgeschlossene Reparatur wird im Protokoll erfasst.']),
    ('new-site-scope',
     ['Wer übernimmt die Wartung der Heizung im Nordhaus?', 'Wer übernimmt die Wartung der Heizung im Südhaus?'],
     ['Who maintains the heating system in North House?', 'Who maintains the heating system in South House?'],
     ['Die Heizungswartung im Nordhaus übernimmt Firma Linde.', 'Die Heizungswartung im Südhaus übernimmt Firma Eiche.', 'Die Aufzugswartung im Nordhaus übernimmt Firma Eiche.', 'Die Heizungswartung im Westhaus übernimmt Firma Birke.', 'Firma Linde übernimmt im Südhaus nur die Gartenpflege.', 'Alle Wartungsverträge werden jährlich geprüft.']),
    ('new-causal-failure',
     ['Welche nachgewiesene Ursache führte zum Abbruch der Sicherung?', 'Welches gleichzeitig beobachtete Ereignis war ausdrücklich nicht die Ursache des Sicherungsabbruchs?'],
     ['Which proven cause made the backup abort?', 'Which simultaneous event was explicitly not the cause of the backup abort?'],
     ['Die Sicherung brach nachweislich wegen eines vollen Zieldatenträgers ab.', 'Gleichzeitig lief eine Druckerwartung; sie war ausdrücklich nicht die Ursache des Sicherungsabbruchs.', 'Die Netzverbindung blieb während der gesamten Sicherung stabil.', 'Ein monatlicher Bericht enthält nur Sicherungszeiten.', 'Die Wiederherstellungsprüfung der Vorwoche war erfolgreich.', 'Die Druckerwartung wurde später ohne Fehler beendet.']),
    ('new-two-source-prerequisites',
     ['Welche beiden Unterlagen werden zusammen für die Schlüsselübergabe benötigt?', 'Welche beiden Unterlagen werden zusammen für die Rückzahlung der Kaution benötigt?'],
     ['Which two documents are jointly required for key handover?', 'Which two documents are jointly required for repayment of the deposit?'],
     ['Für die Schlüsselübergabe ist ein unterschriebenes Übergabeprotokoll erforderlich.', 'Für die Schlüsselübergabe ist zusätzlich eine gültige Vollmacht erforderlich.', 'Für die Kautionsrückzahlung ist das geprüfte Abnahmeprotokoll erforderlich.', 'Für die Kautionsrückzahlung ist zusätzlich eine bestätigte Bankverbindung erforderlich.', 'Ein Besichtigungstermin kann telefonisch vereinbart werden.', 'Die Hausordnung enthält die Ruhezeiten.']),
    ('new-two-source-recovery',
     ['Welche zwei getrennten Schritte sind vor der Wiederherstellung der Datenbank erforderlich?', 'Welche zwei getrennten Schritte sind nach der Wiederherstellung der Datenbank erforderlich?'],
     ['Which two separate steps are required before restoring the database?', 'Which two separate steps are required after restoring the database?'],
     ['Vor der Wiederherstellung muss das Sicherungsarchiv auf Integrität geprüft werden.', 'Vor der Wiederherstellung muss zusätzlich eine isolierte Zielumgebung bereitstehen.', 'Nach der Wiederherstellung muss die Anzahl der Datensätze geprüft werden.', 'Nach der Wiederherstellung müssen zusätzlich die Benutzerberechtigungen geprüft werden.', 'Die Druckereinstellungen sind unabhängig von der Wiederherstellung.', 'Ein Passwortwechsel ersetzt keine Wiederherstellung.']),
]

# Faithful aligned translations of all six passages in each new family.
EN = [
 ['Elisa checks Jonas’s travel expenses.','Klara checks Elisa’s travel expenses.','Jonas checks Klara’s working hours.','Elisa only writes the travel expense policy.','Klara checks supplier invoices.','Jonas submits a vacation schedule.'],
 ['Jonas must not open personnel files; his request was denied.','Klara may open personnel files; her request was approved.','Elisa may open public job advertisements.','Jonas has access to the vacation schedule.','Klara’s access to the invoice archive is blocked.','Personnel files are archived regularly.'],
 ['Approval for order Alpha was revoked on Monday and has not been granted again.','Approval for order Beta remains valid and unchanged.','Order Gamma is still awaiting its first approval.','Only the delivery address for order Delta was corrected.','The approval policy is reviewed every year.','Delivery for order Epsilon has already been completed.'],
 ['The Red edition of the house rules applies through March 2026 inclusive.','The Blue edition takes effect on April 1, 2026 and replaces the Red edition.','The Green edition was only published as a draft.','The garden rules will be discussed in May.','The financial plan applies to the calendar year.','The house rules of the neighbouring East building are independent.'],
 ['The Rosenweg invoice totals 108.32 euros.','The Tulpenweg invoice totals 108.23 euros.','The Nelkenweg invoice totals 180.32 euros.','The Lilienweg quotation totals 108.32 euros and is not an invoice.','The Auenweg invoice totals 1,083.20 euros.','The sum of all invoices is calculated monthly.'],
 ['Invoice North: gross total 119 euros including VAT.','Invoice North: net total 100 euros excluding VAT.','Invoice North: VAT amount 19 euros.','Invoice South: gross total 100 euros.','The West quotation has not yet been invoiced.','The invoice list also includes credit notes.'],
 ['The Red pipe has a diameter of 20 millimetres.','The Blue pipe has a diameter of 20 centimetres.','The Green pipe is 20 metres long; its diameter is unknown.','The Yellow pipe is 2 millimetres thick.','The White pipe has insulation.','The pipes are checked by a specialist company.'],
 ['After the rollback the application is back in production on version 3.2.','Version 3.3 was rolled back because of a defect and is not in production.','Version 3.4 is only available as a test release.','Version 3.1 is stored in the historical archive.','The manual was corrected without changing the version.','The database version is independent of the application.'],
 ['Reference AZ-1042 concerns window repair at North House.','Reference AZ-1024 concerns roof repair at South House.','Reference AZ-1402 concerns heating maintenance.','Reference BZ-1042 concerns garden care.','A general guide explains case references.','The case without a reference has not yet been assigned.'],
 ['Elisa manages the apartment on Müllerstraße.','Jonas manages the apartment on Möllerstraße.','Klara manages the apartment on Malerstraße.','Elisa also manages a garage on Auenweg.','Street cleaning has its own schedule.','Apartments without management are recorded separately.'],
 ['Jonas was informed by Klara about the shutdown.','Klara was informed by Elisa about the shutdown.','Elisa was informed by Jonas about vacation.','Klara only entered the shutdown in the calendar.','Jonas was informed about a different maintenance event.','The shutdown is described in the operations manual.'],
 ['In an acute danger caused by a burst pipe, emergency repair may be ordered without prior approval.','For planned cosmetic repairs, approval is required before placing the order.','A repair quotation alone does not count as an order.','Approval of vacation requests follows a different policy.','Regular inspections are intended to prevent burst pipes.','A completed repair is entered in the log.'],
 ['Linde maintains the heating system in North House.','Eiche maintains the heating system in South House.','Eiche maintains the lift in North House.','Birke maintains the heating system in West House.','Linde only handles garden care in South House.','All maintenance contracts are reviewed annually.'],
 ['The backup demonstrably aborted because the target disk was full.','Printer maintenance ran at the same time; it was explicitly not the cause of the backup abort.','The network connection remained stable throughout the backup.','A monthly report only contains backup times.','Last week’s restore verification was successful.','Printer maintenance later finished without errors.'],
 ['A signed handover report is required for key handover.','A valid power of attorney is additionally required for key handover.','The checked inspection report is required for repayment of the deposit.','Confirmed bank account details are additionally required for repayment of the deposit.','A viewing appointment can be arranged by phone.','The house rules specify quiet hours.'],
 ['Before restoring the database, the backup archive must be checked for integrity.','Before restoring the database, an isolated target environment must also be ready.','After restoring the database, the number of records must be checked.','After restoring the database, user permissions must also be checked.','Printer settings are independent of the restore.','Changing a password does not replace a restore.'],
]


def main():
    original = ROOT.parent / '2026-10-30-german-reranker/corpus.json'
    old = json.loads(original.read_text())
    cases = copy.deepcopy(old['cases'])
    for c in cases:
        c['split'] = 'prior-diagnostic'
    for (family, deq, enq, dep), enp in zip(FAMILIES, EN, strict=True):
        assert len(dep) == len(enp) == 6
        for i in range(2):
            for language, questions, passages in [('de', deq, dep), ('en', enq, enp)]:
                expected = [str(i)] if 'two-source' not in family else [str(2*i), str(2*i+1)]
                cases.append(dict(id=f'{family}-{i+1}-{language}', family=family,
                    pair=f'{family}-{i+1}', language=language, query=questions[i],
                    passages=[dict(id=str(j), text=t) for j,t in enumerate(passages)],
                    expected=expected, split='new-unseen'))
    assert len(cases) == 96 and len({c['family'] for c in cases}) == 24
    corpus = dict(version='multilingual-comparison-v1', cases=cases,
        primary='First seeded permutation only; 48 DE + 48 EN questions in 24 related families.',
        robustness='Reverse permutation is a paired sensitivity check, not independent extra questions.',
        cross_language='Prior16 pairs, DE queries/EN passages and EN queries/DE passages; separate denominator.',
        long_context='First question of every prior family, both languages; six passages padded to6000characters; evidence at beginning/middle/end, bounded512token scoring. Separate48cases; padding authored and frozen before inference.',
        no_answer='Eight paired unrelated questions against the first prior candidate set; report score distributions only, no calibrated abstention threshold.',
        limits='Public synthetic source ranking, preselected candidates; no retrieval recall, answer accuracy, private corpus or production adoption.')
    (ROOT/'corpus.json').write_text(json.dumps(corpus,indent=2,ensure_ascii=False)+'\n')


if __name__ == '__main__':
    main()
