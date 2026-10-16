#!/usr/bin/env python3
"""
ESTÚDIO DE AUDIOLIVROS — VERSÃO STANDALONE
Prepara o guião para síntese TTS externa (quando houver internet)
Gera: ficheiro de segmentos JSON + instruções de gravação
"""

import re
import json
import sys
from pathlib import Path

def analisar_guiao(texto_bruto: str, anunciar_cap: bool = True) -> list[dict]:
    """Parser do guião para segmentos de áudio"""
    linhas = texto_bruto.split('\n')
    segmentos = []

    rate_atual = "-6%"
    pitch_atual = "-1Hz"
    buffer_fala = []

    em_cabecalho_inicial = True
    em_creditos_finais = False
    linhas_processadas = 0
    MAX_CABECALHO = 100

    def descarregar_fala():
        if buffer_fala:
            texto_bloco = " ".join(buffer_fala).strip()
            texto_bloco = re.sub(r'\s+', ' ', texto_bloco)
            if texto_bloco:
                segmentos.append({
                    'tipo': 'fala',
                    'texto': texto_bloco,
                    'rate': rate_atual,
                    'pitch': pitch_atual
                })
            buffer_fala.clear()

    re_separador = re.compile(r'^[=\-_*#]{3,}$')
    re_pausa = re.compile(r'^\[P:\s*(\d+(?:\.\d+)?)s\]$', re.IGNORECASE)
    re_musica = re.compile(r'^\[MÚSICA:.*?\]$', re.IGNORECASE)
    re_narrador = re.compile(r'^\[NARRADOR\s*[—\-:]\s*(.*?)\]$', re.IGNORECASE)
    re_fim = re.compile(r'^\[FIM.*?\]$', re.IGNORECASE)

    re_seccoes_ocultas = re.compile(
        r'^(\d+\.\s*)?(O CONCEITO|A CIÊNCIA|A FERRAMENTA.*|REFLEXÃO|A PONTE.*)$',
        re.IGNORECASE
    )

    re_capitulo_ou_parte = re.compile(
        r'^(CAPÍTULO\s+\d+[A-Z]?\s*[—\-].+|PARTE\s+[A-ZÀ-Ú]+\s*[—\-].+|EPÍLOGO\s*[—\-].+|O SISTEMA MÍNIMO|NOTAS FINAIS)$',
        re.IGNORECASE
    )

    for linha in linhas:
        l = linha.strip()
        if not l:
            continue

        linhas_processadas += 1

        if em_cabecalho_inicial and linhas_processadas > MAX_CABECALHO:
            em_cabecalho_inicial = False

        if re.match(r'^CRÉDITOS DO AUDIOBOOK$', l, re.IGNORECASE):
            descarregar_fala()
            em_creditos_finais = True
            continue

        if em_creditos_finais:
            if l.lower().startswith("obrigado por ouvires"):
                segmentos.append({'tipo': 'pausa', 'segundos': 2.0})
                segmentos.append({'tipo': 'fala', 'texto': l, 'rate': '-10%', 'pitch': '-2Hz'})
            continue

        if re_separador.match(l):
            continue

        if re_capitulo_ou_parte.match(l):
            em_cabecalho_inicial = False
            descarregar_fala()
            segmentos.append({'tipo': 'pausa', 'segundos': 2.0})
            if anunciar_cap:
                titulo_limpo = re.sub(r'\s*[—\-]\s*', '. ', l).capitalize()
                titulo_limpo = re.sub(r'17b', '17 B', titulo_limpo, flags=re.IGNORECASE)
                segmentos.append({
                    'tipo': 'fala',
                    'texto': f"{titulo_limpo}.",
                    'rate': '-10%',
                    'pitch': '-2Hz'
                })
                segmentos.append({'tipo': 'pausa', 'segundos': 2.5})
            continue

        if em_cabecalho_inicial:
            continue

        if re_seccoes_ocultas.match(l):
            descarregar_fala()
            segmentos.append({'tipo': 'pausa', 'segundos': 1.5})
            continue

        if re_fim.match(l):
            descarregar_fala()
            segmentos.append({'tipo': 'pausa', 'segundos': 3.0})
            continue

        if re_musica.match(l):
            descarregar_fala()
            segmentos.append({'tipo': 'pausa', 'segundos': 2.5})
            continue

        m_pausa = re_pausa.match(l)
        if m_pausa:
            descarregar_fala()
            seg = float(m_pausa.group(1))
            segmentos.append({'tipo': 'pausa', 'segundos': seg})
            continue

        m_narrador = re_narrador.match(l)
        if m_narrador:
            descarregar_fala()
            instrucao_tom = m_narrador.group(1).lower()
            if "pausado" in instrucao_tom or "reflex" in instrucao_tom or "despedida" in instrucao_tom:
                rate_atual = "-14%"
                pitch_atual = "-3Hz"
            elif "sóbrio" in instrucao_tom or "grave" in instrucao_tom:
                rate_atual = "-10%"
                pitch_atual = "-4Hz"
            elif "íntimo" in instrucao_tom or "próximo" in instrucao_tom:
                rate_atual = "-8%"
                pitch_atual = "-2Hz"
            elif "informativo" in instrucao_tom or "claro" in instrucao_tom:
                rate_atual = "-2%"
                pitch_atual = "+0Hz"
            elif "prático" in instrucao_tom:
                rate_atual = "-4%"
                pitch_atual = "+0Hz"
            else:
                rate_atual = "-6%"
                pitch_atual = "-1Hz"
            continue

        l_limpa = re.sub(r'\[.*?\]', '', l)
        l_limpa = l_limpa.replace('→', '... ')
        l_limpa = re.sub(r'_{2,}', '...', l_limpa)
        if l_limpa.endswith('—'):
            l_limpa = l_limpa[:-1].strip() + '...'
        else:
            l_limpa = l_limpa.replace(' — ', ', ')

        l_limpa = l_limpa.strip()
        if not l_limpa:
            continue

        if l_limpa[-1] not in '.!?:;,…"\'”':
            l_limpa += '.'

        buffer_fala.append(l_limpa)

    descarregar_fala()
    return segmentos


def agrupar_em_partes(segmentos: list[dict], max_chars: int = 8000) -> list[list[dict]]:
    """Agrupa segmentos em partes para gravação"""
    partes = []
    parte_atual = []
    chars_atuais = 0

    for seg in segmentos:
        if seg['tipo'] == 'fala':
            tam = len(seg['texto'])
            if chars_atuais + tam > max_chars and parte_atual:
                partes.append(parte_atual)
                parte_atual = [seg]
                chars_atuais = tam
            else:
                parte_atual.append(seg)
                chars_atuais += tam
        else:
            parte_atual.append(seg)

    if parte_atual:
        partes.append(parte_atual)
    return partes


def gerar_relatorio(partes: list[list[dict]], nome_base: str):
    """Gera relatório de gravação"""
    total_falas = sum(1 for p in partes for s in p if s['tipo'] == 'fala')
    total_pausas = sum(1 for p in partes for s in p if s['tipo'] == 'pausa')
    total_chars = sum(len(s['texto']) for p in partes for s in p if s['tipo'] == 'fala')

    relatorio = f"""
{'='*60}
RELATÓRIO DE GRAVAÇÃO — {nome_base}
{'='*60}

Total de partes: {len(partes)}
Total de blocos de fala: {total_falas}
Total de pausas: {total_pausas}
Caracteres totais: {total_chars:,}
Duração estimada: {total_chars / 9000:.1f} horas

{'='*60}
INSTRUÇÕES DE GRAVAÇÃO
{'='*60}

1. Voz recomendada: pt-PT-DuarteNeural (masculina) ou pt-PT-RaquelNeural (feminina)
2. Velocidade padrão: -6% (mais lenta que o normal)
3. Tom: ligeiramente mais grave para narração íntima

{'='*60}
ESTRUTURA DAS PARTES
{'='*60}
"""

    for i, parte in enumerate(partes, 1):
        falas = [s for s in parte if s['tipo'] == 'fala']
        pausas = [s for s in parte if s['tipo'] == 'pausa']
        chars = sum(len(s['texto']) for s in falas)
        primeira = falas[0]['texto'][:80] if falas else "(sem fala)"

        relatorio += f"""
Parte {i:02d}:
  - {len(falas)} blocos de fala, {len(pausas)} pausas
  - {chars:,} caracteres (~{chars/900:.0f} minutos)
  - Início: "{primeira}..."
"""

    return relatorio


def main():
    if len(sys.argv) < 2:
        print("Uso: python estudio_standalone.py <ficheiro_guiao.txt>")
        print("Exemplo: python estudio_standalone.py o_arquiteto_de_si_mesmo_audiobook_guiao_completo.txt")
        sys.exit(1)

    ficheiro_guiao = sys.argv[1]
    nome_base = Path(ficheiro_guiao).stem

    print(f"📖 A ler guião: {ficheiro_guiao}")

    with open(ficheiro_guiao, 'r', encoding='utf-8') as f:
        texto = f.read()

    print("🔍 A analisar guião...")
    segmentos = analisar_guiao(texto, anunciar_cap=True)

    print("📦 A agrupar em partes...")
    partes = agrupar_em_partes(segmentos, max_chars=8000)

    # Guardar segmentos em JSON
    json_path = f"{nome_base}_segmentos.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            'segmentos': segmentos,
            'partes': partes,
            'total_partes': len(partes),
            'total_falas': sum(1 for s in segmentos if s['tipo'] == 'fala'),
            'total_pausas': sum(1 for s in segmentos if s['tipo'] == 'pausa'),
        }, f, ensure_ascii=False, indent=2)

    print(f"✅ Segmentos guardados em: {json_path}")

    # Gerar relatório
    relatorio = gerar_relatorio(partes, nome_base)
    relatorio_path = f"{nome_base}_relatorio.txt"
    with open(relatorio_path, 'w', encoding='utf-8') as f:
        f.write(relatorio)

    print(f"✅ Relatório guardado em: {relatorio_path}")

    # Mostrar resumo
    print("\n" + "="*60)
    print("RESUMO")
    print("="*60)
    print(f"Partes: {len(partes)}")
    print(f"Blocos de fala: {sum(1 for s in segmentos if s['tipo'] == 'fala')}")
    print(f"Pausas: {sum(1 for s in segmentos if s['tipo'] == 'pausa')}")
    print(f"Duração estimada: {sum(len(s['texto']) for s in segmentos if s['tipo'] == 'fala') / 9000:.1f} horas")
    print("="*60)

    print("\n📋 PRÓXIMOS PASSOS:")
    print("1. Quando tiveres internet, instala: pip install edge-tts streamlit")
    print("2. Corre a app Streamlit: streamlit run estudio_audiolivros_app.py")
    print("3. Ou usa o JSON para gerar áudio com outra ferramenta TTS")


if __name__ == "__main__":
    main()
