"""Pacchetti di leggi federali da importare in blocco, per settore.

I numeri RS vanno verificati alla prima importazione: se Fedlex non trova un numero, il comando lo segnala
e passa al successivo (`py -m nn importa-pacchetto <nome>`). Per tutta la Raccolta sistematica esiste
`py -m nn importa-catalogo`.
"""

PACCHETTI: dict[str, dict] = {
    "anorma": {
        "descrizione": "Privacy policy, condizioni generali, e-commerce: le leggi che Anorma deve conoscere",
        "atti": [
            ("235.1", "LPD"), ("235.11", "OPDa"), ("235.13", "OCPD"), ("220", "CO"), ("210", "CC"),
            ("241", "LCSl"), ("942.211", "OIP"), ("784.10", "LTC"), ("784.101.1", "OST"),
            ("231.1", "LDA"), ("232.11", "LPM"), ("251", "LCart"), ("943.03", "FiEle"),
            ("221.214.1", "LCC"), ("221.213.11", "OLAL"), ("272", "CPC"), ("291", "LDIP"),
            ("0.275.12", "CLug"), ("641.20", "LIVA"), ("944.0", "LIC"), ("930.11", "LSPro"),
        ],
    },
    "sociali": {
        "descrizione": "Assicurazioni sociali: AVS, AI, IPG, prestazioni complementari, previdenza, malattia, infortuni, disoccupazione, assegni familiari",
        "atti": [
            ("830.1", "LPGA"), ("830.11", "OPGA"),
            ("831.10", "LAVS"), ("831.101", "OAVS"), ("831.108", "Ordinanza sugli adeguamenti (rendite e contributi)"),
            ("831.20", "LAI"), ("831.201", "OAI"),
            ("834.1", "LIPG"), ("834.11", "OIPG"),
            ("831.30", "LPC"), ("831.301", "OPC-AVS/AI"),
            ("831.40", "LPP"), ("831.441.1", "OPP 2"), ("831.435.1", "OPP 1"), ("831.461.3", "OPP 3"),
            ("831.42", "LFLP"), ("831.425", "OLP"),
            ("832.10", "LAMal"), ("832.102", "OAMal"), ("832.112.31", "OPre"), ("832.12", "LVAMal"), ("832.121", "OVAMal"),
            ("832.20", "LAINF"), ("832.202", "OAINF"),
            ("833.1", "LAM"), ("833.11", "OAM"),
            ("837.0", "LADI"), ("837.02", "OADI"),
            ("836.2", "LAFam"), ("836.21", "OAFami"),
        ],
    },
    "assicurazioni-private": {
        "descrizione": "Contratto d'assicurazione e sorveglianza delle assicurazioni, compresi gli intermediari",
        "atti": [
            ("221.229.1", "LCA"), ("961.01", "LSA"), ("961.011", "OS"), ("961.011.1", "OS-FINMA"),
            ("956.1", "LFINMA"), ("955.0", "LRD"),
        ],
    },
    "finanza": {
        "descrizione": "Servizi finanziari, banche, istituti finanziari, infrastrutture, riciclaggio",
        "atti": [
            ("950.1", "LSerFi"), ("950.11", "OSerFi"), ("954.1", "LIsFi"), ("954.11", "OIsFi"),
            ("952.0", "LBCR"), ("952.02", "OBCR"), ("958.1", "LInFi"), ("958.11", "OInFi"),
            ("955.0", "LRD"), ("955.01", "ORD"), ("956.1", "LFINMA"), ("951.31", "LICol"),
        ],
    },
    "lavoro": {
        "descrizione": "Diritto del lavoro pubblico e privato",
        "atti": [("220", "CO"), ("822.11", "LL"), ("822.111", "OLL 1"), ("823.20", "LDist"), ("823.11", "LC"),
                 ("151.1", "LPar")],
    },
}
