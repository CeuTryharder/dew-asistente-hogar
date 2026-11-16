# Guía de Contribución (`CONTRIBUTING.md`)

¡Gracias por contribuir a **Dew — Asistente Doméstico Personal Local-First**!

## Flujo de Desarrollo Local

### 1. Entorno Python y Pipeline del Modelo
```bash
python model_pipeline/calibrate_and_package.py
python model_pipeline/evaluate_quantized_models.py
python -m unittest discover -s tests -v
```

### 2. App Android y Puente Nativo C++ (`llama.cpp` + JNI)
```bash
# Clona llama.cpp en third_party/llama.cpp (gitignorado)
./scripts/setup_native_deps.sh
# Compilar y ejecutar pruebas JVM de Android
gradle :android_app:testDebugUnitTest :android_app:assembleDebug --no-daemon
```

## Reglas para Pull Requests

- **Privacidad y portabilidad:** No incluyas rutas locales absolutas (`C:\Users\...`, `/home/...`), claves, capturas reales, tokens ni correos personales en código, scripts o historial.
- **Guardarraíles deterministas:** Ninguna acción domótica sobre cerraduras/alarmas ni compras debe ejecutarse automáticamente sin confirmación explícita.
- **Concurrencia Android (`StateFlow`):** En `DewViewModel.kt`, nunca llames a `appendLog(`, `pushAssistantReply(`, `_uiState.update` ni `nextId.incrementAndGet()` dentro de bloques `_uiState.update { ... }`.
- **Licencia:** Todas las contribuciones aceptadas se distribuyen bajo la licencia [Apache-2.0](./LICENSE) del repositorio.
