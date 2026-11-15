import { Link } from 'react-router-dom';

import AuthBrand from '../components/AuthBrand.jsx';
import { t } from '../i18n/i18n.jsx';

/// /privacy (v1.12.34): RepLiT's privacy policy, linked from the app, the
/// affiliation form and the Google Play listing. In English, the language of
/// the Data Privacy Act; the page's own words follow the console's language.
///
/// VITE_PRIVACY_CONTACT names who to write to (an email, or an office): set it
/// on Vercel before the Play listing goes live.
const CONTACT =
  (import.meta.env.VITE_PRIVACY_CONTACT || '').trim() ||
  'the Barangay 76 Zone 10 hall, Pasay City (an email for privacy requests will be posted here)';

const EFFECTIVE = '16 November 2026';

export default function Privacy() {
  return (
    <div className="lg rg">
      <AuthBrand />
      <div className="lg-panel rg-panel">
        <article className="lg-form rg-form doc">
          <div className="lg-head">
            <span className="lg-kicker">{t('Privacy policy')}</span>
            <h2 className="lg-title">RepLiT Privacy Policy</h2>
            <p className="lg-sub">Effective {EFFECTIVE}</p>
          </div>

          <p>
            RepLiT is an emergency reporting app for Barangay 76 Zone 10, Pasay City. Residents
            report fires and other emergencies with a photo and their location, and the barangay
            and the responder organizations affiliated with RepLiT (fire volunteers, the Bureau of
            Fire Protection, the Philippine National Police and medical teams) receive them and
            respond. This policy says what RepLiT collects, why, who sees it, how long it is kept,
            and how to delete your account. It follows the Data Privacy Act of 2012 (Republic Act
            No. 10173). RepLiT is developed by M2STZ Crew.
          </p>

          <h3>What RepLiT collects</h3>
          <ul>
            <li>
              <strong>Your account:</strong> your name as on your ID, email address, password
              (kept only in scrambled form by our sign-in provider), and, if you give them, your
              mobile number, date of birth and gender, and the language you choose.
            </li>
            <li>
              <strong>Verification:</strong> confirmation of your email. If you add your National
              ID: photos of your PhilID or ePhilID, its QR code and a selfie, taken with the camera
              in the app. An administrator checks the QR code on the Philippine Statistics
              Authority&apos;s PhilSys Check. The photos are deleted as soon as the review is
              decided.
            </li>
            <li>
              <strong>Your reports:</strong> the photo you take, the time, your location and how
              accurate it is, the agencies you ask for, what you write, and your trust level at
              that moment.
            </li>
            <li>
              <strong>Location:</strong> while you use the app, to place your report and to show
              incidents near you. If you allow location &quot;All the time&quot; (optional), the
              app sends your location about every 15 minutes, only to warn you of a fire within
              100 meters. You can turn this off at any time in your phone&apos;s settings.
            </li>
            <li>
              <strong>Responders&apos; location:</strong> a responder&apos;s position is shared
              every 5 seconds while they go to an incident, until it is marked fire out.
            </li>
            <li>
              <strong>Your phone:</strong> a notification token, the app version and the phone
              model, to send you alerts.
            </li>
            <li>
              <strong>Your answers to alerts,</strong> such as whether you can see a fire reported
              near you.
            </li>
            <li>
              <strong>Records of staff and administrator actions</strong> (who did what and when,
              with the internet address used), so that every decision can be accounted for.
            </li>
          </ul>

          <h3>How it is used</h3>
          <ul>
            <li>To bring your report to the responders who can help, and to coordinate them.</li>
            <li>To tell you how your report is going, and to warn you of fires near you.</li>
            <li>To show responders how far an account is verified, so they can judge a report.</li>
            <li>To keep the barangay&apos;s record of incidents and the teams&apos; post-incident reports.</li>
            <li>To keep RepLiT safe from misuse, for example by refusing temporary email addresses.</li>
          </ul>
          <p>RepLiT does not sell your data, does not show ads and does not use your data for advertising.</p>

          <h3>Who sees it</h3>
          <ul>
            <li>
              <strong>Responders and coordinators</strong> of the agencies your report asks for,
              and the barangay: what they need to respond, including your report, its photo and
              location, your name and your trust level.
            </li>
            <li>
              <strong>Other residents never see</strong> your name, contact details or photos.
              They may see that an incident is active near them, where, and how it is going.
            </li>
            <li>
              <strong>Administrators</strong> of the barangay and the affiliated organizations, to
              manage accounts and to review National IDs.
            </li>
            <li>
              <strong>Service providers</strong> that run RepLiT, only for that purpose: Supabase
              (database, sign-in and file storage), Render (server), Vercel (web console), Google
              Firebase Cloud Messaging (notifications), Brevo (email), DeepSeek (drafts incident
              summaries from the teams&apos; reports; residents&apos; names and contact details are
              not sent), and Mapbox and OpenStreetMap (map images, which see your device&apos;s
              internet address and the area shown).
            </li>
            <li><strong>Authorities,</strong> when the law requires it.</li>
          </ul>
          <p>These providers&apos; servers may be outside the Philippines.</p>

          <h3>How long it is kept</h3>
          <ul>
            <li>Your account: until you delete it.</li>
            <li>National ID photos: until the review is decided, then deleted.</li>
            <li>
              Reports and incident records: kept as the barangay&apos;s record of emergencies, also
              after you delete your account, without your name.
            </li>
            <li>Your alerts and your phones&apos; registrations: deleted with your account.</li>
            <li>Records of staff and administrator actions: kept for accountability.</li>
          </ul>

          <h3>Deleting your account</h3>
          <p>
            In the app: Profile, then Delete my account. On the web:{' '}
            <Link to="/delete-account">reportwhatslit.vercel.app/delete-account</Link>. Your
            sign-in, profile, alerts, phones&apos; registrations, verification records and any
            National ID photos are deleted; your reports stay without your name. A staff account is
            removed by its organization&apos;s administrator.
          </p>

          <h3>Your rights</h3>
          <p>
            Under the Data Privacy Act you may be informed, see your data, correct it (Profile,
            then Edit profile), object, have it deleted (delete your account), and get a copy of
            it. You may also complain to the National Privacy Commission (privacy.gov.ph).
          </p>

          <h3>Age</h3>
          <p>RepLiT accounts are for people 18 and over.</p>

          <h3>Security</h3>
          <p>
            Connections are encrypted. Staff see only what their role needs, and every staff and
            administrator action is recorded.
          </p>

          <h3>Changes</h3>
          <p>
            Changes are posted on this page with a new date. Important ones are also announced in
            the app.
          </p>

          <h3>Contact</h3>
          <p>For questions or requests about your data, contact {CONTACT}.</p>
        </article>
      </div>
    </div>
  );
}
