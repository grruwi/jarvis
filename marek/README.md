---
language:
- pl
license: mit
tags:
- text-to-speech
- tts
- polish
- f5-tts
- voice-cloning
pipeline_tag: text-to-speech
---

# 🎙️ Marek — Polski Model TTS (F5-TTS)

**Marek** to model text-to-speech wytrenowany na języku polskim, oparty na architekturze **F5-TTS**.
Model generuje naturalnie brzmiący głos męski w języku polskim.

## �� Próbki Audio / Audio Samples

Poniższe próbki zostały wygenerowane przez model (bez post-processingu):

| Próbka | Tekst |
|--------|-------|
| [🎵 Lokomotywa — Tuwim](samples/sample_lokomotywa.wav) | *"Stoi na stacji lokomotywa, ciężka, ogromna i pot z niej spływa..."* |
| [🎵 Pan Tadeusz — Mickiewicz](samples/sample_pan_tadeusz.wav) | *"Litwo, ojczyzno moja! ty jesteś jak zdrowie..."* |
| [🎵 Nic dwa razy — Szymborska](samples/sample_szymborska.wav) | *"Nic dwa razy się nie zdarza i nie zdarzy..."* |
| [🎵 Deszcz jesienny — Staff](samples/sample_deszcz.wav) | *"O szyby deszcz dzwoni, deszcz dzwoni jesienny..."* |
| [🎵 Do Matki Polki — Mickiewicz](samples/sample_mickiewicz2.wav) | *"O matko Polko! gdy u syna twego w źrenicach błyszczy..."* |

> 📁 Wszystkie próbki dostępne w folderze [`samples/`](./samples/)

## 📦 Model

- **Architektura**: F5-TTS
- **Język**: Polski 🇵🇱
- **Checkpoint**: `model_205500.pt` (~205 500 kroków treningu)
- **Vocab**: `vocab.txt` (alfabet polski)
- **Format audio wyjściowego**: WAV 24kHz

## 🚀 Użycie / Usage

```python
from f5_tts.api import F5TTS

tts = F5TTS(
    model_type="F5TTS",
    ckpt_file="model_205500.pt",
    vocab_file="vocab.txt",
)

audio, sr, _ = tts.infer(
    ref_file="referencja.wav",       # ~5-10s próbka głosu
    ref_text="Tekst referencyjny.",  # transkrypcja próbki
    gen_text="Dzień dobry! To jest test modelu Marek.",
)
```

## 📂 Pliki w repozytorium

| Plik | Opis |
|------|------|
| `model_205500.pt` | Wagi modelu (główny checkpoint) |
| `vocab.txt` | Słownik znaków dla języka polskiego |
| `samples/` | Przykłady wygenerowanej mowy |

## 📊 Trening

- **Baza**: F5-TTS pretrained (angielski, 1 250 000 kroków)
- **Fine-tuning**: polski dataset mowy (1 845 próbek, ~60 min audio)
- **GPU**: NVIDIA RTX 4060
- **Kroki fine-tuningu**: ~205 500 updates
- **Czas treningu**: ~4–5 dni (ciągły trening, 19–23 marca 2026)
- **Learning rate**: 1e-6 (konserwatywny fine-tuning)
- **Batch size**: 1600 audio frames/GPU

## 📝 Licencja

Ten model jest udostępniany na licencji **MIT** — identycznej jak oryginalny projekt [F5-TTS](https://github.com/SWivid/F5-TTS).

Możesz swobodnie używać, modyfikować i dystrybuować model, również komercyjnie.
Zobacz plik [LICENSE](./LICENSE) po szczegóły.

---
*Wygenerowane przez Kolor AI 🎨*
