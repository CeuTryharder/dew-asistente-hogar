package es.dew.assistant.core

import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import javax.crypto.Mac
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

/**
 * Sincronizador P2P en Red Local Wi-Fi (Android NsdManager `_dew-sync._tcp.`) para Hogares.
 *
 * Compatible a nivel de byte con `dew_core/household_lan_sync.py`:
 *  1. Deriva una clave simétrica de 256 bits mediante `PBKDF2WithHmacSHA256` (100.000 iteraciones)
 *     usando el PIN de 6+ dígitos del hogar y el `householdId`.
 *  2. Firma y verifica cada paquete JSON con `HmacSHA256` en tiempo constante (`MessageDigest.isEqual`).
 *  3. Resuelve conflictos de inventario con la regla CRDT Last-Write-Wins (LWW) comparando
 *     marcas de tiempo ISO-8601 UTC (`updatedAt`).
 */
class DewHouseholdLanSync(
    val nodeId: String,
    val householdId: String,
    pairingCode: String
) {
    companion object {
        private const val PBKDF2_ITERATIONS = 100_000
        private const val KEY_LENGTH_BITS = 256
    }

    private val secretKeyBytes: ByteArray = deriveHouseholdKey(pairingCode, householdId)

    private fun deriveHouseholdKey(pairingCode: String, householdId: String): ByteArray {
        val cleanCode = pairingCode.trim()
        require(cleanCode.length >= 6) {
            "El código de emparejamiento del hogar debe tener al menos 6 caracteres."
        }
        val salt = "dew-lan-sync-v1:${householdId.trim()}".toByteArray(StandardCharsets.UTF_8)
        val spec = PBEKeySpec(cleanCode.toCharArray(), salt, PBKDF2_ITERATIONS, KEY_LENGTH_BITS)
        val factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
        return factory.generateSecret(spec).encoded
    }

    fun computeHmacSha256Hex(canonicalBodyJson: String): String {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(secretKeyBytes, "HmacSHA256"))
        val rawHmac = mac.doFinal(canonicalBodyJson.toByteArray(StandardCharsets.UTF_8))
        return rawHmac.joinToString("") { "%02x".format(it) }
    }

    fun verifyPacketHmac(canonicalBodyJson: String, receivedHexMac: String): Boolean {
        val expectedHex = computeHmacSha256Hex(canonicalBodyJson)
        return MessageDigest.isEqual(
            expectedHex.toByteArray(StandardCharsets.UTF_8),
            receivedHexMac.lowercase().toByteArray(StandardCharsets.UTF_8)
        )
    }

    /**
     * Regla CRDT Last-Write-Wins (LWW): devuelve `true` si el registro remoto (`remoteIsoUtc`)
     * es más reciente que el registro local (`localIsoUtc`).
     */
    fun shouldAcceptRemoteUpdate(localIsoUtc: String?, remoteIsoUtc: String): Boolean {
        if (localIsoUtc.isNullOrBlank()) return true
        return remoteIsoUtc > localIsoUtc
    }
}
