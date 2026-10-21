/**
 * Freigabe eines Hub-Werkzeugs für den Browser: /hub-api/app-call lässt nur Werkzeuge mit Oberfläche oder
 * Tag `flaeche` durch, alles andere weist es mit 403/404 ab (ebenso ein Werkzeug, das es im Hub nicht gibt, weil das
 * Plugin fehlt). Native Ansichten in den Räumen (Bildwerkstatt, Bestellungen, Tagesbrief) sagen dann
 * „Noch nicht eingerichtet.“, statt einen Fehler oder einen toten Knopf zu zeigen.
 */
import { ApiError } from '~/lib/api/client';

/** Gesperrt heißt: der Hub lässt den Browser nicht an das Werkzeug (kein Tag `flaeche`) oder kennt es nicht. */
export const gesperrt = (e: unknown): boolean => e instanceof ApiError && (e.status === 403 || e.status === 404);
