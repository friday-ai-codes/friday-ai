/**
 * Short ID generator for workflow nodes and edges.
 *
 * Generates short, human-friendly IDs that:
 * - Start with a letter (a-z, A-Z)
 * - Contain only alphanumeric characters (a-z, A-Z, 0-9)
 * - Default 3 characters length
 *
 * Used for template variable references like {{nodes.abc.field}}
 */

import { customAlphabet } from 'nanoid'

const letters = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
const alphanumeric = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'

const generateFirstChar = customAlphabet(letters, 1)
const generateRestChars = customAlphabet(alphanumeric, 2)

/**
 * Generate a short ID for workflow nodes/edges.
 * Format: 1 letter + 2 alphanumeric = 3 chars total (e.g., "aB1", "Xyz")
 */
export function generateShortId(): string {
  return generateFirstChar() + generateRestChars()
}
