"""
Dados de demonstração do FarmaSys.

Executado automaticamente na primeira inicialização, quando o banco está vazio:
cadastros de medicamentos reais (com bula e foto gerada), fornecedores,
clientes, notas de entrada com lotes e vendas dos últimos 60 dias — para que
o dashboard, os relatórios e os alertas de estoque já abram "cheios".

Para começar do zero, apague a pasta `data/` (ou use o menu de backup).
"""
import os
import random
import textwrap
from datetime import datetime, timedelta

from flask import current_app

from .db import get_db, inserir, transacao, um
from .utils import mascara_cnpj, mascara_cpf

SEED = 20240101  # semente fixa: exemplos iguais em toda instalação nova


# --------------------------------------------------------------------------- apoio
def _cpf_aleatorio():
    base = [random.randint(0, 9) for _ in range(9)]
    d1 = sum(b * (10 - i) for i, b in enumerate(base)) % 11
    d1 = 0 if d1 < 2 else 11 - d1
    base.append(d1)
    d2 = sum(b * (11 - i) for i, b in enumerate(base)) % 11
    d2 = 0 if d2 < 2 else 11 - d2
    base.append(d2)
    return mascara_cpf("".join(map(str, base)))


def _cnpj_aleatorio():
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    base = [random.randint(0, 9) for _ in range(8)] + [0, 0, 0, 1]

    def digito(nums, pesos):
        soma = sum(n * p for n, p in zip(nums, pesos))
        resto = soma % 11
        return 0 if resto < 2 else 11 - resto

    base.append(digito(base, pesos1))
    base.append(digito(base, pesos2))
    return mascara_cnpj("".join(map(str, base)))


def _ean_aleatorio():
    """EAN-13 fictício com prefixo brasileiro 789."""
    corpo = [7, 8, 9] + [random.randint(0, 9) for _ in range(10)]
    soma = sum(n * (1 if i % 2 == 0 else 3) for i, n in enumerate(corpo))
    dv = (10 - soma % 10) % 10
    return "".join(map(str, corpo)) + str(dv)


def _fonte(tamanho):
    from PIL import ImageFont

    caminhos = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for caminho in caminhos:
        if os.path.exists(caminho):
            try:
                return ImageFont.truetype(caminho, tamanho)
            except OSError:
                continue
    return ImageFont.load_default()


# --------------------------------------------------------------------------- fotos
def _gerar_foto(produto, destino):
    """Gera uma etiqueta visual do medicamento (sem depender de internet)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    cores = {
        "Analgésico e antitérmico": ((59, 130, 246), (37, 99, 235)),
        "Anti-inflamatório": ((239, 68, 68), (185, 28, 28)),
        "Antibiótico": ((16, 185, 129), (5, 150, 105)),
        "Anti-hipertensivo": ((139, 92, 246), (109, 40, 217)),
        "Cardiovascular": ((236, 72, 153), (190, 24, 93)),
        "Diabetes": ((245, 158, 11), (217, 119, 6)),
        "Antialérgico": ((20, 184, 166), (13, 148, 136)),
        "Respiratório e antialérgico": ((2, 132, 199), (3, 105, 161)),
        "Gastroenterologia": ((249, 115, 22), (234, 88, 12)),
        "Sistema nervoso central": ((99, 102, 241), (67, 56, 202)),
        "Hormônios e endocrinologia": ((217, 70, 239), (162, 28, 175)),
        "Vitaminas e suplementos": ((234, 179, 8), (202, 138, 4)),
        "Dermatológico": ((244, 63, 94), (159, 18, 57)),
        "Ginecologia e obstetrícia": ((232, 121, 249), (192, 38, 211)),
    }
    claro, escuro = cores.get(produto.get("classe_terapeutica"), ((59, 130, 246), (37, 99, 235)))
    largo, alto = 640, 640
    img = Image.new("RGB", (largo, alto), claro)
    desenho = ImageDraw.Draw(img)
    for y in range(alto):  # degradê vertical
        t = y / alto
        cor = tuple(int(c1 + (c2 - c1) * t) for c1, c2 in zip(claro, escuro))
        desenho.line([(0, y), (largo, y)], fill=cor)

    # cápsula decorativa
    desenho.rounded_rectangle([110, 96, 530, 216], radius=60, fill=None,
                              outline=(255, 255, 255), width=7)
    desenho.rounded_rectangle([110, 96, 320, 216], radius=60, fill=(255, 255, 255))
    desenho.rectangle([320, 96, 420, 216], fill=(255, 255, 255))

    # iniciais
    iniciais = "".join(p[0] for p in produto["nome"].split()[:2]).upper()
    f_inicial = _fonte(72)
    caixa = desenho.textbbox((0, 0), iniciais, font=f_inicial)
    desenho.text(((largo - (caixa[2] - caixa[0])) / 2, 108), iniciais, font=f_inicial, fill=escuro)

    # nome quebrado em linhas
    f_nome = _fonte(40)
    linhas = textwrap.wrap(produto["nome"], width=20)[:4]
    y = 280
    for linha in linhas:
        caixa = desenho.textbbox((0, 0), linha, font=f_nome)
        desenho.text(((largo - (caixa[2] - caixa[0])) / 2, y), linha, font=f_nome, fill=(255, 255, 255))
        y += 50

    if produto.get("apresentacao"):
        f_apres = _fonte(28)
        apres = produto["apresentacao"]
        caixa = desenho.textbbox((0, 0), apres, font=f_apres)
        desenho.text(((largo - (caixa[2] - caixa[0])) / 2, y + 16), apres, font=f_apres,
                     fill=(255, 255, 255))

    # rodapé com laboratório
    f_lab = _fonte(26)
    lab = produto.get("laboratorio") or ""
    caixa = desenho.textbbox((0, 0), lab, font=f_lab)
    desenho.text(((largo - (caixa[2] - caixa[0])) / 2, alto - 52), lab, font=f_lab, fill=(255, 255, 255))

    os.makedirs(os.path.dirname(destino), exist_ok=True)
    img.save(destino, "JPEG", quality=85, optimize=True)
    return True


# --------------------------------------------------------------------------- cadastros
FORNECEDORES = [
    dict(razao_social="Distribuidora Nacional de Medicamentos Ltda.", nome_fantasia="DinaMed",
         inscricao_estadual="110.042.490.114", telefone="(11) 3456-7890", email="pedidos@dinamed.com.br",
         contato_nome="Ricardo Alves", contato_fone="(11) 98812-3344",
         logradouro="Av. das Nações, 4500", numero="4500", bairro="Distrito Industrial",
         cidade="São Paulo", uf="SP", site="www.dinamed.com.br",
         observacoes="Distribuidor principal. Entrega em 48h."),
    dict(razao_social="PanVale Farma Distribuidora S.A.", nome_fantasia="PanVale",
         inscricao_estadual="062.318.775.009", telefone="(31) 3222-1188", email="comercial@panvale.com.br",
         contato_nome="Juliana Prado", contato_fone="(31) 99145-7788",
         logradouro="Rod. Fernão Dias, km 482", numero="S/N", bairro="Galpões Betim",
         cidade="Betim", uf="MG", site="www.panvale.com.br",
         observacoes="Bons preços em genéricos."),
    dict(razao_social="Santa Catarina Pharma Logística Ltda.", nome_fantasia="SC Pharma",
         inscricao_estadual="255.907.114", telefone="(48) 3033-4455", email="vendas@scpharma.com.br",
         contato_nome="Marcos Steffens", contato_fone="(48) 99677-2211",
         logradouro="Rua das Laranjeiras, 210", numero="210", bairro="Km 4",
         cidade="Florianópolis", uf="SC", site="www.scpharma.com.br",
         observacoes="Foco em dermocosméticos e correlatos."),
]

CLIENTES = [
    "Maria Aparecida Souza", "João Batista Lima", "Ana Cláudia Ferreira", "Carlos Eduardo Pereira",
    "Fernanda Gonçalves", "Roberto Almeida Nunes", "Patrícia Moreira", "José Carlos Rodrigues",
    "Simone Barbosa", "Luiz Fernando Alves", "Márcia Regina Teixeira", "Antônio Vilela Júnior",
    "Cleide dos Santos", "Paulo Sérgio Carvalho", "Vandra Lopes", "Edson Marques Pinto",
    "Rosângela Dias", "Wagner Fiuza", "Lúcia Helena Campos", "Geraldo Magela", "Terezinha Bueno",
    "Ricardo Menezes Tavares",
]


def _produtos():
    """Lista de medicamentos de exemplo (dados didáticos; bulas resumidas)."""
    return [
        dict(codigo="MED0001", nome="Dipirona Monoidratada 500mg", principio_ativo="Dipirona monoidratada",
             laboratorio="Neo Química", classe="Analgésico e antitérmico", apresentacao="Comprimido - cx 10",
             concentracao="500 mg", tarja="livre", custo=4.20, venda=8.90, minimo=20,
             bula=dict(indicacoes="Dor de cabeça, dor dental, cólica menstrual, febre e dor pós-operatória.",
                       posologia="Adultos: 1 comprimido de 500 mg a 1 g, até 4 vezes por dia, com intervalo mínimo de 4 horas.",
                       contraindicacoes="Hipersensibilidade à dipirona; histórico de alterações graves do sangue; doenças do fígado.",
                       efeitos_adversos="Raros: reações alérgicas, queda de pressão, broncoespasmo; muito raros: alterações hematológicas.",
                       advertencias="Pode mascarar sinais de infecção. Pacientes asmáticos devem usar com cautela.",
                       interacoes="Potencializa efeito de warfarina; reduz efeito de lítio e zidovudina.",
                       gravidez="Evitar no 1º trimestre e no fim da gestação; usar por curto período e sob orientação médica.",
                       sobredoagem="Sintomas: tontura, hipotensão, taquicardia, insuficiência respiratória. Procure atendimento imediato.",
                       armazenamento="Manter em local seco, ao abrigo da luz, abaixo de 30 °C.")),
        dict(codigo="MED0002", nome="Paracetamol 750mg", principio_ativo="Paracetamol",
             laboratorio="EMS", classe="Analgésico e antitérmico", apresentacao="Comprimido - cx 20",
             concentracao="750 mg", tarja="livre", custo=6.10, venda=12.50, minimo=15,
             bula=dict(indicacoes="Dor leve a moderada e febre.",
                       posologia="Adultos: 1 comprimido a cada 6 horas; máximo 4 g por dia.",
                       contraindicacoes="Hipersensibilidade ao paracetamol; insuficiência hepática grave.",
                       efeitos_adversos="Em doses usuais, raros: náuseas, prurido; em superdose, dano hepático.",
                       advertencias="Atenção a outros medicamentos com paracetamol na fórmula.",
                       interacoes="Risco aumentado de hepatotoxicidade com álcool, warfarina e rifampicina.",
                       gravidez="Pode ser usado na gestação nas doses recomendadas.",
                       sobredoagem="Urgência médica: antídoto N-acetilcisteína nas primeiras horas.",
                       armazenamento="Manter abaixo de 30 °C, em local seco.")),
        dict(codigo="MED0003", nome="Ibuprofeno 600mg", principio_ativo="Ibuprofeno",
             laboratorio="Prati-Donaduzzi", classe="Anti-inflamatório", apresentacao="Comprimido revestido - cx 20",
             concentracao="600 mg", tarja="amarela", custo=9.80, venda=19.90, minimo=12,
             bula=dict(indicacoes="Inflamação, dor articular, lombalgia, tendinite, dor pós-operatória e febre.",
                       posologia="1 comprimido 3 vezes ao dia, após as refeições, pelo menor tempo possível.",
                       contraindicacoes="Úlcera gástrica ativa, sangramento digestivo, 3º trimestre de gravidez, após cirurgia de revascularização.",
                       efeitos_adversos="Azia, dor abdominal, náuseas; risco de sangramento e renais em uso prolongado.",
                       advertencias="Usar com alimentos. Suspender se houver dor de estômago persistente ou fezes escuras.",
                       interacoes="Anticoagulantes, AAS, corticoides, lítio e anti-hipertensivos.",
                       gravidez="Contraindicado no 3º trimestre; evitar no 1º e 2º trimestres.",
                       sobredoagem="Procure atendimento imediato; lavagem gástrica nas primeiras horas.",
                       armazenamento="Manter em local seco, ao abrigo da umidade.")),
        dict(codigo="MED0004", nome="Nimesulida 100mg", principio_ativo="Nimesulida",
             laboratorio="Cimed", classe="Anti-inflamatório", apresentacao="Comprimido - cx 12",
             concentracao="100 mg", tarja="amarela", custo=5.40, venda=11.90, minimo=10,
             bula=dict(indicacoes="Dor e inflamação (artrose, lombalgia, tendinite, dor dental).",
                       posologia="1 comprimido 2 vezes ao dia, após as refeições, por até 5 dias.",
                       contraindicacoes="Hepatopatias, úlcera péptica ativa, sangramento, gravidez e amamentação.",
                       efeitos_adversos="Desconforto gástrico, tontura, prurido; raro de dano hepático.",
                       advertencias="Não ultrapassar 150 mg por dia. Suspender se surgirem sinais de hepatite.",
                       interacoes="Anticoagulantes, AAS, metotrexato, lítio.",
                       gravidez="Contraindicado em qualquer trimestre.",
                       sobredoagem="Atendimento de urgência; não existe antídoto específico.",
                       armazenamento="Manter abaixo de 30 °C.")),
        dict(codigo="MED0005", nome="Amoxicilina 500mg", principio_ativo="Amoxicilina tri-hidratada",
             laboratorio="EMS", classe="Antibiótico", apresentacao="Cápsula - cx 21",
             concentracao="500 mg", tarja="amarela", custo=18.40, venda=34.90, minimo=10,
             bula=dict(indicacoes="Infecções bacterianas: ouvido, sinusite, garganta, pulmão, pele e trato urinário.",
                       posologia="Adultos: 500 mg a cada 8 horas, por 7 a 10 dias, conforme orientação médica.",
                       contraindicacoes="Hipersensibilidade a penicilinas; mononucleose infecciosa.",
                       efeitos_adversos="Diarreia, náuseas, rash cutâneo; raro: anafilaxia.",
                       advertencias="Concluir todo o tratamento, mesmo após melhora. Informar alergias a penicilina.",
                       interacoes="Metotrexato, probenecida, anticoncepcionais orais.",
                       gravidez="Considerado seguro na gravidez, sob prescrição.",
                       sobredoagem="Procure atendimento; lavagem gástrica e suporte.",
                       armazenamento="Manter entre 15 °C e 30 °C, em local seco.")),
        dict(codigo="MED0006", nome="Azitromicina 500mg", principio_ativo="Azitromicina di-hidratada",
             laboratorio="EMS", classe="Antibiótico", apresentacao="Comprimido revestido - cx 5",
             concentracao="500 mg", tarja="amarela", custo=22.10, venda=42.90, minimo=8,
             bula=dict(indicacoes="Infecções respiratórias, de ouvido, pele e trato urinário causadas por microrganismos sensíveis.",
                       posologia="1 comprimido ao dia, por 3 a 5 dias, com 1 hora de antecedência ou 2 horas após as refeições.",
                       contraindicacoes="Hipersensibilidade à azitromicina ou a outros macrolídeos; hepatopatia grave.",
                       efeitos_adversos="Diarreia, dor abdominal, náuseas, tontura.",
                       advertencias="Pode prolongar o intervalo QT; informar uso de outros medicamentos.",
                       interacoes="Antiácidos, warfarina, digoxina, ergotamina.",
                       gravidez="Usar se necessário, avaliando risco-benefício.",
                       sobredoagem="Atendimento imediato com suporte e monitorização.",
                       armazenamento="Manter abaixo de 30 °C, ao abrigo da luz.")),
        dict(codigo="MED0007", nome="Omeprazol 20mg", principio_ativo="Omeprazol",
             laboratorio="Medley", classe="Gastroenterologia", apresentacao="Cápsula - cx 28",
             concentracao="20 mg", tarja="amarela", custo=11.30, venda=24.90, minimo=15,
             bula=dict(indicacoes="Úlcera gástrica e duodenal, refluxo gastroesofágico, esofagite e proteção gástrica.",
                       posologia="1 cápsula em jejum, de manhã, por 4 a 8 semanas.",
                       contraindicacoes="Hipersensibilidade ao omeprazol ou benzimidazóis substituídos.",
                       efeitos_adversos="Cefaleia, flatulência, náuseas, dor abdominal, diarreia.",
                       advertencias="Uso prolongado pode reduzir magnésio, cálcio e vitamina B12.",
                       interacoes="Clopidogrel, cetoconazol, itraconazol, metotrexato, warfarina.",
                       gravidez="Usar apenas se necessário; estudos não mostraram risco relevante.",
                       sobredoagem="Sintomas limitados; tratamento sintomático.",
                       armazenamento="Manter em local seco, abaixo de 30 °C.")),
        dict(codigo="MED0008", nome="Dramin B6 50mg/25mg", principio_ativo="Dimenidrinato + piridoxina",
             laboratorio="Takeda", classe="Gastroenterologia", apresentacao="Comprimido - cx 20",
             concentracao="50 mg / 25 mg", tarja="livre", custo=14.60, venda=27.90, minimo=8,
             bula=dict(indicacoes="Náuseas, vômitos e tontura relacionados a labirintopatias e enjoo de movimento.",
                       posologia="1 a 2 comprimidos, 30 minutos antes da viagem, repetindo a cada 4 a 8 horas se necessário.",
                       contraindicacoes="Hipersensibilidade aos componentes; glaucoma; úlcera péptica; obstrução pilórica.",
                       efeitos_adversos="Sonolência, boca seca, visão turva, taquicardia.",
                       advertencias="Pode causar sonolência; não dirigir após o uso.",
                       interacoes="Depressores do SNC, álcool, inibidores da MAO.",
                       gravidez="Consultar médico antes do uso na gravidez.",
                       sobredoagem="Sintomas anticolinérgicos; procure atendimento.",
                       armazenamento="Manter em local seco, ao abrigo da luz.")),
        dict(codigo="MED0009", nome="Losartana Potássica 50mg", principio_ativo="Losartana potássica",
             laboratorio="EMS", classe="Anti-hipertensivo", apresentacao="Comprimido revestido - cx 30",
             concentracao="50 mg", tarja="amarela", custo=9.70, venda=21.50, minimo=20,
             bula=dict(indicacoes="Hipertensão arterial e proteção renal em diabéticos tipo 2.",
                       posologia="1 comprimido ao dia; pode ser ajustado pelo médico até 100 mg/dia.",
                       contraindicacoes="Gravidez, hipersensibilidade, coadministração com aliskirene em diabéticos.",
                       efeitos_adversos="Tontura, fadiga, cefaleia; raro: elevação de potássio.",
                       advertencias="Não usar medicamentos com potássio sem orientação. Avaliar função renal.",
                       interacoes="AINEs, lítio, diuréticos poupadores de potássio, varfarina.",
                       gravidez="Contraindicado: pode causar lesão fetal e morte.",
                       sobredoagem="Hipotensão e taquicardia; atendimento médico.",
                       armazenamento="Manter abaixo de 30 °C, em local seco.")),
        dict(codigo="MED0010", nome="Enalapril 10mg", principio_ativo="Maleato de enalapril",
             laboratorio="Neo Química", classe="Anti-hipertensivo", apresentacao="Comprimido - cx 30",
             concentracao="10 mg", tarja="amarela", custo=7.90, venda=17.90, minimo=15,
             bula=dict(indicacoes="Hipertensão arterial, insuficiência cardíaca e proteção cardiovascular.",
                       posologia="Inicial: 5 mg ao dia; manutenção conforme orientação médica.",
                       contraindicacoes="Gravidez, angioedema prévio, hipersensibilidade a IECAs.",
                       efeitos_adversos="Tosse seca, tontura, cefaleia, hipercalemia; raro: angioedema.",
                       advertencias="Suspender em caso de angioedema e procurar atendimento.",
                       interacoes="AINEs, diuréticos poupadores de potássio, lítio, sartanas.",
                       gravidez="Contraindicado (teratogenicidade comprovada).",
                       sobredoagem="Hipotensão acentuada; atendimento com suporte.",
                       armazenamento="Manter em local seco, abaixo de 30 °C.")),
        dict(codigo="MED0011", nome="Metformina 850mg", principio_ativo="Cloridrato de metformina",
             laboratorio="Merck", classe="Diabetes", apresentacao="Comprimido revestido - cx 30",
             concentracao="850 mg", tarja="amarela", custo=12.40, venda=26.90, minimo=15,
             bula=dict(indicacoes="Diabetes mellitus tipo 2, isolada ou associada a outros hipoglicemiantes.",
                       posologia="1 comprimido 2 a 3 vezes ao dia, durante ou após as refeições.",
                       contraindicacoes="Insuficiência renal grave, acidose metabólica, hepatopatia grave, consumo excessivo de álcool.",
                       efeitos_adversos="Náuseas, diarreia, desconforto abdominal, gosto metálico; raro: acidose láctica.",
                       advertencias="Suspender 48h antes de exames com contraste iodado e em cirurgias.",
                       interacoes="Iodo, corticoides, diuréticos, álcool.",
                       gravidez="Uso permitido apenas com controle médico no período gestacional.",
                       sobredoagem="Risco de acidose láctica: atendimento de urgência.",
                       armazenamento="Manter em local seco, abaixo de 30 °C.")),
        dict(codigo="MED0012", nome="Sinvastatina 20mg", principio_ativo="Sinvastatina",
             laboratorio="Medley", classe="Cardiovascular", apresentacao="Comprimido revestido - cx 30",
             concentracao="20 mg", tarja="amarela", custo=10.60, venda=23.90, minimo=12,
             bula=dict(indicacoes="Hipercolesterolemia e prevenção de eventos cardiovasculares.",
                       posologia="1 comprimido à noite; dose ajustada pelo médico (10 a 80 mg).",
                       contraindicacoes="Doença hepática ativa, gravidez e amamentação, hipersensibilidade.",
                       efeitos_adversos="Mialgia, cefaleia, dor abdominal, elevação de enzimas hepáticas.",
                       advertencias="Informar dor muscular inexplicável; evitar grandes quantidades de suco de toranja.",
                       interacoes="Itraconazol, eritromicina, claritromicina, fibratos, ciclosporina.",
                       gravidez="Contraindicada.",
                       sobredoagem="Tratamento sintomático; hemodiálise não é eficaz.",
                       armazenamento="Manter em local seco, abaixo de 30 °C.")),
        dict(codigo="MED0013", nome="AAS Protect 100mg", principio_ativo="Ácido acetilsalicílico",
             laboratorio="Bayer", classe="Cardiovascular", apresentacao="Comprimido gastrorresistente - cx 30",
             concentracao="100 mg", tarja="amarela", custo=13.20, venda=28.90, minimo=10,
             bula=dict(indicacoes="Prevenção secundária de infarto e AVC; proteção cardiovascular.",
                       posologia="1 comprimido ao dia, preferencialmente após as refeições.",
                       contraindicacoes="Úlcera ativa, sangramento, gravidez no 3º trimestre, crianças com viroses.",
                       efeitos_adversos="Azia, sangramento digestivo, hematoma, zumbido.",
                       advertencias="Suspender 7 dias antes de cirurgias. Informar qualquer sangramento.",
                       interacoes="Anticoagulantes, ibuprofeno, álcool, AINEs.",
                       gravidez="Contraindicado no 3º trimestre.",
                       sobredoagem="Risco de intoxicação grave: atendimento imediato.",
                       armazenamento="Manter em local seco, ao abrigo da umidade.")),
        dict(codigo="MED0014", nome="Loratadina 10mg", principio_ativo="Loratadina",
             laboratorio="Neo Química", classe="Antialérgico", apresentacao="Comprimido - cx 12",
             concentracao="10 mg", tarja="livre", custo=5.60, venda=12.90, minimo=15,
             bula=dict(indicacoes="Rinite alérgica, urticária e sintomas de alergias da pele.",
                       posologia="1 comprimido ao dia, com ou sem alimentos.",
                       contraindicacoes="Hipersensibilidade; amamentação; menor de 2 anos (soluções com outro sabor).",
                       efeitos_adversos="Sonolência leve, cefaleia, boca seca, fadiga.",
                       advertencias="Reduzir dose em insuficiência hepática.",
                       interacoes="Cetoconazol, eritromicina, inibidores da CYP3A4.",
                       gravidez="Usar apenas se necessário; compatível com amamentação em baixas doses.",
                       sobredoagem="Pode causar sedação; procure orientação médica.",
                       armazenamento="Manter abaixo de 30 °C.")),
        dict(codigo="MED0015", nome="Dexclorfeniramina 2mg", principio_ativo="Maleato de dexclorfeniramina",
             laboratorio="Cimed", classe="Antialérgico", apresentacao="Comprimido - cx 20",
             concentracao="2 mg", tarja="livre", custo=6.80, venda=13.90, minimo=10,
             bula=dict(indicacoes="Rinite alérgica, urticária, conjuntivite alérgica e prurido.",
                       posologia="Adultos: 1 comprimido a cada 6 horas; criança conforme orientação.",
                       contraindicacoes="Hipersensibilidade; glaucoma; úlcera péptica; uso concomitante com IMAO.",
                       efeitos_adversos="Sonolência intensa, boca seca, visão turva, retenção urinária.",
                       advertencias="Pode causar forte sonolência; não dirigir.",
                       interacoes="Depressores do SNC, álcool, anticolinérgicos.",
                       gravidez="Evitar durante a gestação e amamentação.",
                       sobredoagem="Sintomas anticolinérgicos; atendimento médico.",
                       armazenamento="Manter em local seco, ao abrigo da luz.")),
        dict(codigo="MED0016", nome="Prednisona 20mg", principio_ativo="Prednisona",
             laboratorio="Prati-Donaduzzi", classe="Sistema nervoso central", apresentacao="Comprimido - cx 10",
             concentracao="20 mg", tarja="amarela", custo=8.30, venda=18.90, minimo=8,
             bula=dict(indicacoes="Processos inflamatórios e alérgicos, doenças autoimunes e crises asmáticas.",
                       posologia="Dose diária única pela manhã, conforme prescrição, com redução gradual.",
                       contraindicacoes="Infecções fúngicas sistêmicas, hipersensibilidade, vacinas com vírus vivos.",
                       efeitos_adversos="Insônia, aumento do apetite, retenção hídrica, hiperglicemia, osteoporose no longo prazo.",
                       advertencias="Não suspender abruptamente. Informar sinais de infecção.",
                       interacoes="AINEs, antidiabéticos, rifampicina, anticoagulantes.",
                       gravidez="Usar apenas se necessário e sob supervisão médica.",
                       sobredoagem="Tratamento sintomático e suporte.",
                       armazenamento="Manter em local seco, abaixo de 30 °C.")),
        dict(codigo="MED0017", nome="Fluoxetina 20mg", principio_ativo="Cloridrato de fluoxetina",
             laboratorio="EMS", classe="Sistema nervoso central", apresentacao="Cápsula - cx 30",
             concentracao="20 mg", tarja="vermelha", custo=14.90, venda=32.90, minimo=8,
             bula=dict(indicacoes="Depressão, transtorno obsessivo-compulsivo e bulimia nervosa.",
                       posologia="20 mg ao dia pela manhã; dose ajustada pelo médico.",
                       contraindicacoes="Uso concomitante com IMAO (intervalo mínimo de 5 semanas).",
                       efeitos_adversos="Insônia, náusea, ansiedade, sudorese, disfunção sexual.",
                       advertencias="Monitorar humor no início do tratamento; informar pensamentos suicidas.",
                       interacoes="IMAO, triptans, lítio, varfarina, TCA.",
                       gravidez="Avaliar risco-benefício com o médico.",
                       sobredoagem="Procure atendimento imediato.",
                       armazenamento="Manter em local seco, ao abrigo da umidade.")),
        dict(codigo="MED0018", nome="Clonazepam 2mg", principio_ativo="Clonazepam",
             laboratorio="Roche", classe="Sistema nervoso central", apresentacao="Comprimido - cx 30",
             concentracao="2mg", tarja="preta", controlado=1, custo=16.20, venda=36.90, minimo=5,
             bula=dict(indicacoes="Epilepsia e transtorno de pânico, conforme prescrição especial.",
                       posologia="Dose inicial baixa, titulada pelo médico; dose única à noite ou fracionada.",
                       contraindicacoes="Hipersensibilidade a benzodiazepínicos; insuficiência respiratória grave; miastenia.",
                       efeitos_adversos="Sonolência, tontura, fadiga, comprometimento motor, dependência.",
                       advertencias="Medicamento controlado: uso contínuo pode gerar dependência. Não suspender bruscamente.",
                       interacoes="Álcool, opioides, antidepressivos, antifúngicos azólicos.",
                       gravidez="Contraindicado no 1º trimestre; risco de malformações.",
                       sobredoagem="Risco grave com depressão do SNC: SAMU 192 imediatamente.",
                       armazenamento="Guardar em local seguro e trancado, fora do alcance de crianças.")),
        dict(codigo="MED0019", nome="Levotiroxina Sódica 50mcg", principio_ativo="Levotiroxina sódica",
             laboratorio="Merck", classe="Hormônios e endocrinologia", apresentacao="Comprimido - cx 30",
             concentracao="50 mcg", tarja="amarela", custo=11.10, venda=24.50, minimo=12,
             bula=dict(indicacoes="Hipotireoidismo e reposição hormonal tireoidiana.",
                       posologia="Em jejum, 30 a 60 minutos antes do café, conforme prescrição.",
                       contraindicacoes="Infarto agudo, tireotoxicose não tratada, hipersensibilidade.",
                       efeitos_adversos="Em dose excessiva: taquicardia, insônia, perda de peso, tremor.",
                       advertencias="Manter dose constante e fazer exames de TSH periodicamente.",
                       interacoes="Ferro, cálcio, antiácidos, varfarina, sulfonilureias.",
                       gravidez="Uso indispensável na gestação: dose frequentemente aumentada.",
                       sobredoagem="Sinais de hipertireoidismo: procurar médico.",
                       armazenamento="Manter em local seco, ao abrigo da luz.")),
        dict(codigo="MED0020", nome="Addera D3 7.000UI", principio_ativo="Colecalciferol (vitamina D3)",
             laboratorio="Cobasic", classe="Vitaminas e suplementos", apresentacao="Cápsula mole - cx 8",
             concentracao="7.000 UI", tarja="livre", custo=19.40, venda=39.90, minimo=10,
             bula=dict(indicacoes="Prevenção e tratamento da deficiência de vitamina D.",
                       posologia="1 cápsula semanal, ou conforme orientação médica.",
                       contraindicacoes="Hipersensibilidade; hipercalcemia; sarcoidose.",
                       efeitos_adversos="Raramente: náusea, constipação, hipercalcemia com uso excessivo.",
                       advertencias="Não exceder a dose prescrita; avaliar cálcio sérico em uso prolongado.",
                       interacoes="Diuréticos tiazídicos, glicosídeos cardíacos, corticoides.",
                       gravidez="Compatível nas doses recomendadas.",
                       sobredoagem="Hipercalcemia: suspender e consultar o médico.",
                       armazenamento="Manter em local seco, abaixo de 30 °C.")),
        dict(codigo="MED0021", nome="Complexo B - 60 cápsulas", principio_ativo="Vitaminas B1, B2, B6 e B12",
             laboratorio="Cimed", classe="Vitaminas e suplementos", apresentacao="Cápsula - frasco 60",
             concentracao="Polivitamínico B", tarja="livre", custo=17.80, venda=36.90, minimo=8,
             bula=dict(indicacoes="Suplementação em deficiências de vitaminas do complexo B e exaustão física.",
                       posologia="1 cápsula ao dia, preferencialmente após o almoço.",
                       contraindicacoes="Hipersensibilidade aos componentes; doença de Leber.",
                       efeitos_adversos="Raros: náusea, cefaleia, urina de coloração amarela intensa (inofensiva).",
                       advertencias="Suplemento não substitui alimentação equilibrada.",
                       interacoes="Levodopa, fenobarbital, clorfeniramina.",
                       gravidez="Seguro nas doses recomendadas; consultar médico.",
                       sobredoagem="Excesso é eliminado pela urina; sem risco relevante.",
                       armazenamento="Manter em local seco, ao abrigo da luz.")),
        dict(codigo="MED0022", nome="Dorflex - 36 comprimidos", principio_ativo="Dipirona + orfenadrina + cafeína",
             laboratorio="Sanofi", classe="Analgésico e antitérmico", apresentacao="Comprimido - cx 36",
             concentracao="300 mg / 35 mg / 50 mg", tarja="livre", custo=22.60, venda=42.90, minimo=10,
             bula=dict(indicacoes="Cefaleia tensional, dor muscular e enxaqueca leve.",
                       posologia="1 a 2 comprimidos, até 3 vezes ao dia.",
                       contraindicacoes="Hipersensibilidade a dipirona; glaucoma; miastenia; problemas urinários.",
                       efeitos_adversos="Sono, boca seca, tontura, retenção urinária.",
                       advertencias="Pode causar sonolência; evitar álcool.",
                       interacoes="Álcool, sedativos, outros anticolinérgicos.",
                       gravidez="Evitar no 1º trimestre; usar por curto período.",
                       sobredoagem="Procure atendimento imediato.",
                       armazenamento="Manter abaixo de 30 °C.")),
        dict(codigo="MED0023", nome="Buscopan Composto - 20 comprimidos", principio_ativo="Butilbrometo de escopolamina + dipirona",
             laboratorio="Boehringer", classe="Gastroenterologia", apresentacao="Comprimido - cx 20",
             concentracao="10 mg / 500 mg", tarja="livre", custo=21.30, venda=39.90, minimo=8,
             bula=dict(indicacoes="Cólica abdominal, cólica menstrual e distúrbios espásticos digestivos.",
                       posologia="1 a 2 comprimidos ao dia, conforme necessidade, com água.",
                       contraindicacoes="Hipersensibilidade, glaucoma, miastenia, obstrução intestinal.",
                       efeitos_adversos="Boca seca, taquicardia, retenção urinária, sonolência.",
                       advertencias="Não usar por período prolongado sem avaliação médica.",
                       interacoes="Anticolinérgicos, antidepressivos, anti-histamínicos.",
                       gravidez="Consultar médico antes do uso.",
                       sobredoagem="Procure atendimento.",
                       armazenamento="Manter em local seco, abaixo de 30 °C.")),
        dict(codigo="MED0024", nome="Cetoconazol Creme 2%", principio_ativo="Cetoconazol",
             laboratorio="Medley", classe="Dermatológico", apresentacao="Creme - bisnaga 30 g",
             concentracao="2%", tarja="amarela", custo=9.90, venda=21.90, minimo=10,
             bula=dict(indicacoes="Dermatomicoses: tinea pedis, corporis, cruris, pityriasis versicolor.",
                       posologia="Aplicar fina camada na área afetada, 1x ao dia, por 2 a 4 semanas.",
                       contraindicacoes="Hipersensibilidade ao cetoconazol ou imidazóis.",
                       efeitos_adversos="Irritação local, prurido, sensação de queimação.",
                       advertencias="Somente uso externo. Evitar contato com olhos e mucosas.",
                       interacoes="Nenhuma relevante por via tópica.",
                       gravidez="Compatível; evitar áreas extensas na gestação.",
                       sobredoagem="Uso tópico: sem risco relevante.",
                       armazenamento="Manter abaixo de 30 °C. Não congelar.")),
        dict(codigo="MED0025", nome="Aerolin Spray 100mcg", principio_ativo="Sulfato de salbutamol",
             laboratorio="GSK", classe="Respiratório e antialérgico", apresentacao="Aerosol 200 doses",
             concentracao="100 mcg/dose", tarja="amarela", custo=26.70, venda=48.90, minimo=6,
             bula=dict(indicacoes="Broncoespasmo na asma e DPOC; alívio rápido dos sintomas.",
                       posologia="1 a 2 inalações em caso de crise; até 8 doses/dia sob orientação.",
                       contraindicacoes="Hipersensibilidade ao salbutamol.",
                       efeitos_adversos="Tremor, taquicardia, cefaleia, nervosismo, hipocalemia.",
                       advertencias="Aumento da necessidade indica piora da asma: procurar médico.",
                       interacoes="Betabloqueadores, diuréticos, corticoides, MAO.",
                       gravidez="Usar se necessário; preferir via inalatória.",
                       sobredoagem="Taquicardia e tremor: procurar atendimento.",
                       armazenamento="Manter em local seco, abaixo de 30 °C. Não perfurar a lata.")),
        dict(codigo="MED0026", nome="Puran T4 50mcg", principio_ativo="Levotiroxina sódica",
             laboratorio="Sanofi", classe="Hormônios e endocrinologia", apresentacao="Comprimido - cx 30",
             concentracao="50 mcg", tarja="amarela", custo=15.30, venda=31.90, minimo=10,
             bula=dict(indicacoes="Hipotireoidismo (substitutivo e de reposição).",
                       posologia="Em jejum, com água, 30 minutos antes do café.",
                       contraindicacoes="Infarto agudo não tratado; tireotoxicose; hipersensibilidade.",
                       efeitos_adversos="Em excesso: palpitação, insônia, perda de peso, irritabilidade.",
                       advertencias="Manter o mesmo laboratório sempre que possível para estabilidade da dose.",
                       interacoes="Ferro, cálcio, soja, antácidos, carbamazepina.",
                       gravidez="Indispensável na gestação; requer ajuste de dose.",
                       sobredoagem="Sinais de hipertireoidismo: consultar médico.",
                       armazenamento="Manter em local seco, ao abrigo da luz e umidade.")),
        dict(codigo="MED0027", nome="Insulina NPH 100UI/mL", principio_ativo="Insulina humana NPH",
             laboratorio="Novo Nordisk", classe="Diabetes", apresentacao="Frasco-ampola 10 mL",
             concentracao="100 UI/mL", tarja="amarela", custo=42.30, venda=78.90, minimo=5,
             bula=dict(indicacoes="Diabetes mellitus tipo 1 e 2, com prescrição médica.",
                       posologia="Subcutânea, conforme prescrição; frasco deve ser agitado suavemente.",
                       contraindicacoes="Hipo-glicemia; hipersensibilidade à insulina.",
                       efeitos_adversos="Hipo-glicemia, lipodistrofia no local da aplicação, reações alérgicas.",
                       advertencias="Validade após aberto: 28 dias em temperatura ambiente. Monitorar glicemia.",
                       interacoes="Betabloqueadores, corticoides, álcool, sulfonilureias.",
                       gravidez="Necessário ajuste contínuo com acompanhamento médico.",
                       sobredoagem="Hipo-glicemia: ingerir carboidrato simples; se desmaiar, glucagon/SAMU.",
                       armazenamento="Refrigerado (2 °C a 8 °C). Após aberto, pode ficar a até 25 °C por 28 dias.")),
        dict(codigo="MED0028", nome="Ciclo 21 - 21 comprimidos", principio_ativo="Levonorgestrel + etinilestradiol",
             laboratorio="União Química", classe="Ginecologia e obstetrícia", apresentacao="Comprimido - cx 21",
             concentracao="0,15 mg / 0,03 mg", tarja="vermelha", custo=8.70, venda=19.90, minimo=10,
             bula=dict(indicacoes="Controle da natalidade; regulação do ciclo menstrual.",
                       posologia="1 comprimido por dia, sempre no mesmo horário, por 21 dias, seguidos de 7 dias de pausa.",
                       contraindicacoes="Tromboembolismo, enxaqueca com aura, tabagismo acima dos 35 anos, doença hepática.",
                       efeitos_adversos="Náuseas, dor de cabeça, retenção hídrica, sangramento irregular.",
                       advertencias="Fumantes acima de 35 anos devem usar método alternativo. Informar dor no peito ou perna.",
                       interacoes="Antibióticos rifamicinas, anticonvulsivantes, erva de São João.",
                       gravidez="Contraindicado; suspender 1 mês antes de tentar gravidez.",
                       sobredoagem="Náuseas e sangramento irregular; consultar médico.",
                       armazenamento="Manter em local seco, abaixo de 30 °C.")),
    ]


# --------------------------------------------------------------------------- execução
def semear_se_necessario():
    """Popula o banco quando vazio. Retorna True se os dados foram criados."""
    db = get_db()
    if db.execute("SELECT COUNT(*) FROM produtos").fetchone()[0] > 0:
        return False

    random.seed(SEED)
    try:
        _semear()
    except Exception:
        db.rollback()
        raise
    return True


def _semear():
    db = get_db()
    admin = db.execute("SELECT id FROM usuarios WHERE perfil = 'admin' LIMIT 1").fetchone()
    caixa = db.execute("SELECT id FROM usuarios WHERE perfil = 'caixa' LIMIT 1").fetchone()
    gerente = db.execute("SELECT id FROM usuarios WHERE perfil = 'gerente' LIMIT 1").fetchone()
    admin_id = admin["id"] if admin else None
    operador_id = caixa["id"] if caixa else admin_id
    operador2_id = gerente["id"] if gerente else admin_id

    # ----- empresa de demonstração
    db.execute("UPDATE parametros SET valor = ? WHERE chave = 'empresa_nome'",
               ("Farmácia Vida Plena",))
    db.execute("UPDATE parametros SET valor = ? WHERE chave = 'empresa_fantasia'",
               ("Vida Plena Drogaria",))
    db.execute("UPDATE parametros SET valor = ? WHERE chave = 'empresa_cnpj'",
               ("12.345.678/0001-95",))
    db.execute("UPDATE parametros SET valor = ? WHERE chave = 'empresa_endereco'",
               ("Av. Brasil, 1500 - Centro",))
    db.execute("UPDATE parametros SET valor = ? WHERE chave = 'empresa_cidade'",
               ("Sua Cidade - UF",))
    db.execute("UPDATE parametros SET valor = ? WHERE chave = 'empresa_telefone'",
               ("(00) 3222-1000",))
    db.commit()

    # ----- fornecedores
    ids_fornecedores = []
    with transacao():
        for f in FORNECEDORES:
            f = dict(f)
            f["cnpj"] = _cnpj_aleatorio()
            ids_fornecedores.append(inserir("fornecedores", f))

    # ----- clientes
    ids_clientes = []
    with transacao():
        for i, nome in enumerate(CLIENTES):
            nasc = datetime(1945 + (i * 2) % 55, (i % 12) + 1, ((i * 7) % 27) + 1)
            limite = random.choice([0, 0, 200, 300, 500, 800, 1000])
            ids_clientes.append(inserir("clientes", {
                "nome": nome,
                "cpf": _cpf_aleatorio(),
                "data_nascimento": nasc.strftime("%Y-%m-%d"),
                "celular": f"(00) 9{random.randint(1000, 9999)}-{random.randint(1000, 9999)}",
                "email": _email(nome),
                "logradouro": random.choice(["Rua das Flores", "Av. Independência", "Rua XV de Novembro",
                                             "Travessa São João", "Av. Beira-Mar"]),
                "numero": str(random.randint(20, 2500)),
                "bairro": random.choice(["Centro", "Jardim América", "Vila Nova", "Boa Vista", "Santa Rita"]),
                "cidade": "Sua Cidade",
                "uf": "UF",
                "limite_credito": float(limite),
            }))

    # ----- produtos, fotos e bulas
    produtos = _produtos()
    ids_produtos = []
    with transacao():
        for p in produtos:
            produto_id = inserir("produtos", {
                "codigo": p["codigo"],
                "ean": _ean_aleatorio(),
                "nome": p["nome"],
                "principio_ativo": p["principio_ativo"],
                "laboratorio": p["laboratorio"],
                "classe_terapeutica": p["classe"],
                "apresentacao": p["apresentacao"],
                "concentracao": p["concentracao"],
                "tarja": p["tarja"],
                "controlado": p.get("controlado", 0),
                "receita_obrigatoria": 1 if p["tarja"] in ("amarela", "vermelha", "preta") else 0,
                "registro_anvisa": f"1.{random.randint(1000, 9999)}.{random.randint(1000, 9999)}.{random.randint(1, 9)}-{random.randint(1, 9)}",
                "ncm": "3004.90.99",
                "unidade": "UN",
                "preco_custo": p["custo"],
                "preco_venda": p["venda"],
                "estoque": 0,
                "estoque_minimo": p["minimo"],
                "localizacao": f"{random.choice('ABCD')}-{random.randint(1, 24):02d}",
            })
            ids_produtos.append(produto_id)
            bula = {k: v for k, v in p["bula"].items() if v}
            bula["produto_id"] = produto_id
            bula["atualizada_em"] = datetime.now().strftime("%Y-%m-%d")
            inserir("bulas", bula)

            # foto gerada localmente
            destino = os.path.join(current_app.config["UPLOAD_DIR"], "produtos",
                                   f"{p['codigo'].lower()}.jpg")
            if _gerar_foto({**p, "classe_terapeutica": p["classe"]}, destino):
                inserir("produto_fotos", {"produto_id": produto_id, "arquivo": f"{p['codigo'].lower()}.jpg",
                                          "principal": 1})

    # ----- notas de entrada com lotes
    usuarios = [i for i in (admin_id, operador_id, operador2_id) if i]
    with transacao():
        for indice, produto_id in enumerate(ids_produtos):
            p = produtos[indice]
            fornecedor_id = random.choice(ids_fornecedores)
            qtd_inicial = random.randint(60, 220)
            # dois lotes por produto
            lote_a = f"L{random.randint(1000, 9999)}A"
            lote_b = f"L{random.randint(1000, 9999)}B"
            val_a = _data_futura(random.randint(220, 700))
            val_b = _data_futura(random.randint(700, 1200))
            _entrada_direta(produto_id, qtd_inicial // 2, lote_a, val_a, p["custo"],
                            fornecedor_id, f"NF {20000 + indice}", random.choice(usuarios))
            _entrada_direta(produto_id, qtd_inicial - qtd_inicial // 2, lote_b, val_b, p["custo"],
                            fornecedor_id, f"NF {20000 + indice}", random.choice(usuarios))

        # três notas de entrada recentes (aba "Notas de entrada")
        for n in range(3):
            fornecedor_id = ids_fornecedores[n % len(ids_fornecedores)]
            entrada_id = inserir("entradas", {
                "numero": f"E{datetime.now().year}-{n + 1:06d}",
                "fornecedor_id": fornecedor_id,
                "data_emissao": _data_passada(random.randint(5, 40)),
                "usuario_id": random.choice(usuarios),
                "total": 0.0,
                "observacao": "Pedido de reposição semanal",
            })
            soma = 0.0
            for _ in range(random.randint(4, 8)):
                indice = random.randrange(len(ids_produtos))
                qtd = random.randint(10, 40)
                custo = produtos[indice]["custo"]
                _entrada_direta(ids_produtos[indice], qtd, f"NR{n}{random.randint(100, 999)}",
                                _data_futura(random.randint(240, 900)), custo, fornecedor_id,
                                f"E{datetime.now().year}-{n + 1:06d}", random.choice(usuarios), entrada_id)
                soma += qtd * custo
            db.execute("UPDATE entradas SET total = ? WHERE id = ?", (round(soma, 2), entrada_id))

    # ----- vendas dos últimos 60 dias
    from .services import ErroNegocio, criar_venda

    formas = (["dinheiro"] * 34 + ["pix"] * 24 + ["debito"] * 18 + ["credito"] * 11
              + ["ticket"] * 6 + ["ficha"] * 7)
    agora_dt = datetime.now()
    criadas = 0
    for n in range(230):
        cliente_id = random.choice(ids_clientes) if random.random() < 0.55 else None
        forma = random.choice(formas)
        if forma == "ficha":
            cliente_id = cliente_id or random.choice(ids_clientes)
        qtd_itens = random.choices([1, 2, 3, 4, 5], weights=[38, 28, 18, 10, 6])[0]
        escolhidos = random.sample(range(len(ids_produtos)), qtd_itens)
        itens = []
        for indice in escolhidos:
            produto_id = ids_produtos[indice]
            disponivel = um("SELECT estoque FROM produtos WHERE id = ?", (produto_id,))[0]
            if disponivel < 4:
                continue
            qtd = random.choices([1, 2, 3], weights=[74, 20, 6])[0]
            preco = produtos[indice]["venda"]
            desconto = round(preco * qtd * 0.05, 2) if random.random() < 0.07 else 0
            itens.append({"produto_id": produto_id, "quantidade": qtd,
                          "preco_unitario": preco, "desconto": desconto})
        if not itens:
            continue

        if forma == "ficha":
            pagamentos = []  # dívida lançada na ficha do cliente
        else:
            pagamentos = [{"forma": forma, "valor": 0, "parcelas": 1}]

        # data/hora com picos de manhã e tarde
        dia = agora_dt - timedelta(days=random.randint(0, 59))
        hora = random.choices(range(8, 20), weights=[6, 9, 11, 10, 8, 7, 9, 10, 11, 10, 8, 5])[0]
        momento = dia.replace(hour=hora, minute=random.randint(0, 59), second=random.randint(0, 59))

        try:
            # pagamento aberto: preenche com o total após saber o resultado
            resultado = criar_venda({
                "cliente_id": cliente_id,
                "itens": itens,
                "desconto": 0,
                "pagamentos": [{"forma": forma, "valor": 10 ** 6, "parcelas": 1}] if forma != "ficha" else [],
                "terminal": random.choice(["PDV-01", "PDV-02"]),
                "observacao": "",
            }, {"id": random.choice(usuarios)})
        except ErroNegocio:
            continue

        # corrige valor pago e insere o pagamento real
        with transacao():
            db.execute("UPDATE vendas SET valor_pago = ?, troco = 0, data = ?, cupom_impresso = ? WHERE id = ?",
                       (resultado["total"], momento.strftime("%Y-%m-%d %H:%M:%S"),
                        1 if random.random() < 0.4 else 0, resultado["id"]))
            db.execute("DELETE FROM pagamentos WHERE venda_id = ?", (resultado["id"],))
            if forma == "ficha":
                # o criar_venda já lançou a dívida; apenas retroage a data do lançamento
                db.execute("""UPDATE fichas SET criado_em = ?, vencimento = ?
                              WHERE venda_id = ? AND tipo = 'lancamento'""",
                           (momento.strftime("%Y-%m-%d %H:%M:%S"),
                            (momento + timedelta(days=30)).strftime("%Y-%m-%d"),
                            resultado["id"]))
            else:
                inserir("pagamentos", {"venda_id": resultado["id"], "forma": forma,
                                       "valor": resultado["total"], "parcelas": 1})
            # movimentações com a data da venda (mantém o histórico coerente)
            db.execute("UPDATE movimentacoes SET criado_em = ? WHERE ref_id = ? AND tipo = 'venda'",
                       (momento.strftime("%Y-%m-%d %H:%M:%S"), resultado["id"]))
        criadas += 1

    # ----- situações de alerta (estoque baixo, validade próxima e vencida)
    with transacao():
        indices_alerta = (0, 3, 6, 12, 20, 24)
        for i, indice in enumerate(indices_alerta):
            if indice >= len(ids_produtos):
                continue
            produto_id = ids_produtos[indice]
            p = produtos[indice]
            # lote perto do vencimento
            _entrada_direta(produto_id, random.randint(4, 9), f"LV{i:03d}",
                            _data_futura(random.randint(10, 55)), p["custo"],
                            random.choice(ids_fornecedores), f"NF UR{i}", random.choice(usuarios))
            # leva o saldo para abaixo do mínimo (reposição)
            disponivel = db.execute("SELECT estoque FROM produtos WHERE id = ?",
                                    (produto_id,)).fetchone()[0]
            meta = max(0, p["minimo"] - random.randint(2, 6))
            if disponivel > meta:
                _zerar_lotes(produto_id, disponivel - meta, "ajuste", operador_id,
                             "Inventário - saldo abaixo do mínimo para reposição")
        # lote já vencido (exibe o alerta de validade vencida)
        _entrada_direta(ids_produtos[14], 4, "LVENC01", _data_futura(-12),
                        produtos[14]["custo"], ids_fornecedores[0], "NF URX", admin_id)

    # ----- pagamentos de ficha (conta corrente em movimento)
    from .services import pagar_ficha

    with transacao():
        devedores = db.execute(
            """SELECT c.id FROM clientes c
               WHERE c.saldo_credito > 30 AND EXISTS
                 (SELECT 1 FROM fichas f WHERE f.cliente_id = c.id AND f.tipo = 'lancamento')
               ORDER BY RANDOM() LIMIT 5""").fetchall()
        for d in devedores:
            saldo = float(um("SELECT saldo_credito FROM clientes WHERE id = ?", (d["id"],))[0])
            valor = round(min(saldo * random.uniform(0.3, 0.8), saldo), 2)
            try:
                pagar_ficha(d["id"], valor, {"id": operador_id},
                            descricao="Pagamento parcial da ficha", forma="dinheiro")
            except Exception:
                pass

    # ----- terminais de exemplo
    with transacao():
        for nome, ip in (("PDV-01", "192.168.0.10"), ("PDV-02", "192.168.0.11"),
                         ("GERENCIA", "192.168.0.5")):
            if not um("SELECT id FROM terminais WHERE nome = ?", (nome,)):
                inserir("terminais", {"nome": nome, "ip": ip, "usuario_id": admin_id})

    db.commit()
    print(f"  ✓ Dados de exemplo criados: {len(ids_produtos)} medicamentos, "
          f"{len(ids_clientes)} clientes, {len(ids_fornecedores)} fornecedores, {criadas} vendas.")


def _email(nome):
    partes = [p for p in nome.lower().split() if len(p) > 2]
    return f"{partes[0]}.{partes[-1]}@email.com.br"


def _data_futura(dias):
    return (datetime.now() + timedelta(days=dias)).strftime("%Y-%m-%d")


def _data_passada(dias):
    return (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")


def _zerar_lotes(produto_id, quantidade, tipo, usuario_id, motivo):
    """Baixa saldo consumindo os lotes de validade mais distante (preserva alertas)."""
    db = get_db()
    restante = int(quantidade)
    if restante <= 0:
        return
    lotes = db.execute(
        """SELECT id, quantidade FROM lotes WHERE produto_id = ? AND quantidade > 0
           ORDER BY date(COALESCE(validade, '2999-12-31')) DESC, id DESC""",
        (produto_id,),
    ).fetchall()
    for lote in lotes:
        if restante <= 0:
            break
        tirar = min(restante, lote["quantidade"])
        db.execute("UPDATE lotes SET quantidade = quantidade - ? WHERE id = ?", (tirar, lote["id"]))
        restante -= tirar
    saldo = db.execute("SELECT estoque FROM produtos WHERE id = ?", (produto_id,)).fetchone()[0]
    saldo = max(0, saldo - (int(quantidade) - restante))
    db.execute("UPDATE produtos SET estoque = ? WHERE id = ?", (saldo, produto_id))
    inserir("movimentacoes", {
        "produto_id": produto_id, "tipo": tipo, "quantidade": -(int(quantidade) - restante),
        "saldo_apos": saldo, "usuario_id": usuario_id, "observacao": motivo,
    })


def _entrada_direta(produto_id, quantidade, lote, validade, custo, fornecedor_id, nota,
                    usuario_id, entrada_id=None):
    """Entrada de mercadoria com data retroativa (mantém lotes e movimentos coerentes)."""
    db = get_db()
    inserir("lotes", {
        "produto_id": produto_id, "lote": lote, "validade": validade,
        "quantidade": int(quantidade), "preco_custo": custo,
        "fornecedor_id": fornecedor_id, "nota_fiscal": nota,
    })
    saldo = db.execute("SELECT estoque FROM produtos WHERE id = ?", (produto_id,)).fetchone()[0] + quantidade
    db.execute("UPDATE produtos SET estoque = ? WHERE id = ?", (saldo, produto_id))
    inserir("movimentacoes", {
        "produto_id": produto_id, "tipo": "entrada", "quantidade": int(quantidade),
        "saldo_apos": saldo, "tipo_ref": "entrada", "ref_id": entrada_id,
        "usuario_id": usuario_id, "observacao": f"NF {nota}",
    })
