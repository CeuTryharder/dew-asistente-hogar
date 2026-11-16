# Política de Seguridad (`SECURITY.md`)

## Arquitectura de Privacidad y Guardarraíles de Dew

**Dew** está diseñado bajo un enfoque **Local-First**:
- La base de datos doméstica (`dew_core/storage_and_memory.py`), la gestión de inventario, la domótica LAN y los expedientes locales permanecen en el dispositivo.
- Las consultas abiertas externas opcionales nunca reciben memorias personales ni datos del hogar del usuario.
- Las mezclas químicas peligrosas (`CHEM_GUARD`), consignas térmicas extremas (`16–26 °C`) y acciones domóticas críticas (`CRITICAL_SECURITY_DOMAINS`, como cerraduras) requieren validación determinista y confirmación explícita del usuario en pantalla.

## Reporte de Vulnerabilidades

Si detectas una vulnerabilidad de seguridad, fuga de datos, fallo en los guardarraíles o ejecución no confirmada de comandos:

1. **No abras un issue público** con detalles explotables.
2. Reporta el problema de forma privada a través de **GitHub Security Advisories**:
   `https://github.com/CeuTryharder/dew-asistente-hogar/security/advisories/new`

Por favor incluye pasos mínimos de reproducción, entorno afectado (Python / Android / C++ JNI) e impacto estimado.
