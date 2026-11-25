CREATE OR REPLACE VIEW izicerfa_supervision.journal WITH (security_barrier = true) AS
SELECT e.id::text AS id, e.recu_le AS received, e.source_izicerfa AS site,
       e.event_id AS event, e.donation_id AS donation, NULLIF(e.subscription_id,'0') AS subscription,
       e.statut_payload AS status, e.etat_traitement AS worker, e.dernier_code_erreur AS error,
       COALESCE(NULLIF(e.payload #>> '{data,donation,donor,email}',''),
                NULLIF(e.payload #>> '{data,donation,donor_email}',''),
                NULLIF(e.payload #>> '{data,donation,email}',''),
                NULLIF(e.payload #>> '{data,donor,email}',''),
                NULLIF(e.payload #>> '{data,subscription,donor,email}','')) AS email,
       e.payload #>> '{data,donation,amount}' AS amount,
       e.payload #>> '{data,donation,currency}' AS currency,
       e.payload #>> '{data,donation,createdAt}' AS source_created,
       e.payload #>> '{data,donation,date_comptable}' AS source_accounting,
       e.payload #>> '{data,donation,date}' AS source_date,
       a.donation_id_initial AS initial_donation,
       greatest(e.recu_le,e.traite_le,a.mis_a_jour_le) AS changed,
       e.payload #>> '{data,donation,mode_de_versement}' AS declared_method,
       e.payload #>> '{data,donation,payment_gateway}' AS payment_gateway,
       COALESCE(NULLIF(e.payload #>> '{data,donation,payment_method_details,type}',''),
                NULLIF(e.payload #>> '{data,donation,payment_method,type}',''),
                CASE WHEN jsonb_typeof((e.payload #> '{data,donation,payment_method}')::jsonb) = 'string'
                     THEN e.payload #>> '{data,donation,payment_method}' END) AS instrument,
       CASE WHEN e.payload #>> '{data,donation,stripe_error_code}' = 'card_declined'
            THEN 'card_declined' END AS card_error
FROM public.evenements_webhook_recus e
LEFT JOIN public.etats_abonnements_izicerfa a
    ON a.source_izicerfa = e.source_izicerfa AND a.subscription_id = NULLIF(e.subscription_id,'0')
WHERE e.source_izicerfa IN ('AIU','ENIO')
  AND e.recu_le >= timestamptz '2026-11-24 13:30:00+00';
