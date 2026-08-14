/** محاكاة حجز وارد — بتعدّي من نفس بوابة القناة، عشان الرحلة تتشاف كاملة. */

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";

import { ApiError, post } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { addDays, toISO } from "@/lib/format";
import type { Channel, ChannelBookingRow } from "@/lib/types";
import { Button, Modal, cx, inputClass } from "./ui";

const NAMES: [string, string][] = [
  ["Omar", "Khaled"],
  ["Laura", "Bennett"],
  ["ندى", "سليم"],
  ["Marco", "Bianchi"],
  ["Hussein", "Adly"],
];

export default function SimulateBooking({
  channel,
  onDone,
}: {
  channel: Channel;
  onDone: () => void;
}) {
  const { t, locale } = useI18n();
  const [open, setOpen] = useState(false);

  const [roomId, setRoomId] = useState("");
  const [arrival, setArrival] = useState(() => toISO(addDays(new Date(), 10)));
  const [departure, setDeparture] = useState(() => toISO(addDays(new Date(), 12)));
  const [adults, setAdults] = useState(2);
  const [result, setResult] = useState<ChannelBookingRow | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setRoomId(channel.mappings[0]?.external_room_id ?? "");
    setResult(null);
    setError(null);
  }, [open, channel]);

  const send = useMutation({
    mutationFn: () => {
      const [first, last] = NAMES[Math.floor(Math.random() * NAMES.length)];
      const stamp = Date.now().toString().slice(-6);
      return post<ChannelBookingRow>(`/channels/${channel.source}/bookings`, {
        external_reference: `${channel.source.slice(0, 3)}-${stamp}`,
        action: "NEW",
        external_room_id: roomId,
        arrival_date: arrival,
        departure_date: departure,
        adults,
        children: 0,
        guest: {
          first_name: first,
          last_name: last,
          phone: `+2010${stamp}${Math.floor(Math.random() * 10)}`,
        },
      });
    },
    onSuccess: (row) => {
      setResult(row);
      setError(null);
      onDone();
    },
    onError: (err) => {
      setResult(null);
      setError(err instanceof ApiError ? err.text(locale) : t("state.error"));
    },
  });

  const tone =
    result?.status === "PROCESSED"
      ? "border-good/40 bg-good/10 text-good"
      : "border-warn/40 bg-warn/10 text-warn";

  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}>
        {t("ch.simulate")}
      </Button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title={`${t("ch.simulate")} — ${locale === "ar" ? channel.name_ar : channel.name_en}`}
        footer={
          <>
            <Button onClick={() => setOpen(false)}>{t("action.close")}</Button>
            <Button
              variant="primary"
              disabled={send.isPending || !roomId.trim()}
              onClick={() => send.mutate()}
            >
              {t("ch.simulateSend")}
            </Button>
          </>
        }
      >
        <p className="text-[12.5px] text-muted leading-relaxed mb-4">{t("ch.simulateHint")}</p>

        <label className="flex flex-col gap-1.5 mb-4">
          <span className="text-[13px] font-bold text-ink-2">{t("ch.roomId")}</span>
          <select
            className={cx(inputClass, "num")}
            value={roomId}
            onChange={(e) => setRoomId(e.target.value)}
          >
            {channel.mappings.map((m) => (
              <option key={m.id} value={m.external_room_id}>
                {m.external_room_id} — {m.category_name_ar}
              </option>
            ))}
            <option value="UNKNOWN-ROOM">UNKNOWN-ROOM</option>
          </select>
        </label>

        <div className="grid grid-cols-3 gap-3 mb-4">
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-bold text-ink-2">{t("book.arrival")}</span>
            <input
              type="date"
              className={cx(inputClass, "num")}
              value={arrival}
              onChange={(e) => e.target.value && setArrival(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-bold text-ink-2">{t("book.departure")}</span>
            <input
              type="date"
              className={cx(inputClass, "num")}
              value={departure}
              onChange={(e) => e.target.value && setDeparture(e.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[13px] font-bold text-ink-2">{t("book.adults")}</span>
            <input
              type="number"
              min={1}
              className={cx(inputClass, "num")}
              value={adults}
              onChange={(e) => setAdults(Math.max(1, Number(e.target.value) || 1))}
            />
          </label>
        </div>

        {result && (
          <div className={cx("rounded-[6px] border px-3.5 py-2.5 text-[12.5px]", tone)}>
            <div className="font-bold">
              {t(`ch.${result.status}`)}
              {result.reservation_code && (
                <span className="num ms-2">{result.reservation_code}</span>
              )}
            </div>
            {result.error && <div className="mt-0.5">{result.error}</div>}
          </div>
        )}

        {error && (
          <div className="rounded-[6px] border border-bad/40 bg-bad/10 px-3.5 py-2.5 text-[12.5px] text-bad">
            {error}
          </div>
        )}
      </Modal>
    </>
  );
}
