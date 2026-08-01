require('dotenv').config();
const express = require('express');
const cors = require('cors');
const path = require('path');
const crypto = require('crypto');
const Razorpay = require('razorpay');
const fs = require('fs');
const db = require('./database');

const app = express();
const PORT = process.env.PORT || 5000;

// Setup Razorpay
const RAZORPAY_KEY_ID = process.env.RAZORPAY_KEY_ID;
const RAZORPAY_KEY_SECRET = process.env.RAZORPAY_KEY_SECRET;

if (!RAZORPAY_KEY_ID || !RAZORPAY_KEY_SECRET) {
  console.error("FATAL ERROR: RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET environment variables are required.");
  process.exit(1);
}

const razorpay = new Razorpay({
  key_id: RAZORPAY_KEY_ID,
  key_secret: RAZORPAY_KEY_SECRET
});

// Middleware
app.use(cors());
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// Serve frontend website static files
app.use(express.static(path.join(__dirname, 'public')));

// Helper to generate a unique license key
function generateLicenseKey() {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // Avoid ambiguous chars like O, 0, I, 1
  const part = () => Array.from({ length: 4 }, () => chars[Math.floor(Math.random() * chars.length)]).join('');
  return `VELO-${part()}-${part()}-${part()}-${part()}`;
}

// API: Ping to wake up server
app.get('/api/ping', (req, res) => {
  res.json({ success: true, status: 'online' });
});

// API: Check if username or email is valid and unique
app.post('/api/check-user', async (req, res) => {
  try {
    const { username, email } = req.body;
    
    if (!username || !email) {
      return res.status(400).json({ success: false, message: 'Username and email are required.' });
    }

    // Simple email validation
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(email)) {
      return res.status(400).json({ success: false, message: 'Please enter a valid email address.' });
    }

    const existingUser = await db.getSubscription(username);
    const existingEmail = await db.getSubscription(email);

    if (existingUser || existingEmail) {
      return res.status(400).json({ 
        success: false, 
        message: 'Username or Email is already registered. If you want to renew, please log in inside the app.' 
      });
    }

    res.json({ success: true, message: 'Username and email are available.' });
  } catch (error) {
    console.error('Check user error:', error);
    res.status(500).json({ success: false, message: 'Internal server error.' });
  }
});

// API: Create Razorpay Order
app.post('/api/payment/create-order', async (req, res) => {
  try {
    const { username, email, is_renewal } = req.body;

    if (!username || !email) {
      return res.status(400).json({ success: false, message: 'Username and email are required.' });
    }

    // If it's a renewal, the user must already exist
    if (is_renewal) {
      const sub = await db.getSubscription(username);
      if (!sub) {
        return res.status(404).json({ success: false, message: 'User not found. Cannot renew.' });
      }
    }

    const amount = 828; // Amount in INR (69 rupees/month * 12 months)
    const options = {
      amount: Math.round(amount * 100), // in paise
      currency: 'INR',
      receipt: `rec_${username.substring(0, 10)}_${Date.now()}`,
      notes: {
        username: username,
        email: email,
        is_renewal: is_renewal ? 'true' : 'false'
      }
    };

    console.log(`[Payment] Creating Razorpay order for ${username} (${email}). Renewal: ${is_renewal || 'false'}`);
    const order = await razorpay.orders.create(options);

    res.json({
      success: true,
      razorpay_order_id: order.id,
      amount: order.amount,
      currency: order.currency,
      razorpay_key: RAZORPAY_KEY_ID
    });
  } catch (error) {
    console.error('Razorpay order creation error:', error);
    res.status(500).json({ success: false, message: 'Failed to create payment order.', details: error.message });
  }
});

// API: Verify Razorpay Payment and Activate/Renew Subscription
app.post('/api/payment/verify', async (req, res) => {
  try {
    const { 
      razorpay_order_id, 
      razorpay_payment_id, 
      razorpay_signature,
      username,
      email,
      is_renewal 
    } = req.body;

    // Verify signature
    const hmac = crypto.createHmac('sha256', RAZORPAY_KEY_SECRET);
    hmac.update(`${razorpay_order_id}|${razorpay_payment_id}`);
    const generated_signature = hmac.digest('hex');

    if (generated_signature !== razorpay_signature) {
      console.error('[Payment] Signature verification failed!');
      return res.status(400).json({ success: false, message: 'Payment verification failed. Invalid signature.' });
    }

    console.log(`[Payment] Signature verified for order ${razorpay_order_id}`);

    // Signature matches, process subscription
    let subscription;
    let licenseKey;

    if (is_renewal === 'true' || is_renewal === true) {
      // Renew existing
      subscription = await db.renewSubscription(username);
      licenseKey = subscription.license_key;
      console.log(`[Subscription] Renewed subscription for user: ${username}, expires: ${subscription.expires_at}`);
    } else {
      // Check if user already got created in database during window between check and pay
      const existing = await db.getSubscription(username);
      if (existing) {
        subscription = existing;
        licenseKey = existing.license_key;
      } else {
        // Create new
        licenseKey = generateLicenseKey();
        subscription = await db.createSubscription(username, email, licenseKey);
        console.log(`[Subscription] Created subscription for user: ${username}, Key: ${licenseKey}`);
      }
    }

    res.json({
      success: true,
      message: is_renewal ? 'Subscription renewed successfully!' : 'Subscription activated successfully!',
      username: subscription.username,
      email: subscription.email,
      license_key: licenseKey,
      expires_at: subscription.expires_at
    });
  } catch (error) {
    console.error('Payment verification error:', error);
    res.status(500).json({ success: false, message: 'Internal server error processing payment.', details: error.message });
  }
});

// API: Desktop Client License Activation
app.post('/api/license/activate', async (req, res) => {
  try {
    const { username, license_key, machine_id } = req.body;

    if (!username || !license_key || !machine_id) {
      return res.status(400).json({ success: false, message: 'Username, license key, and machine ID are required.' });
    }

    const result = await db.activateLicense(username, license_key, machine_id);
    res.json(result);
  } catch (error) {
    console.error('License activation error:', error);
    res.status(500).json({ success: false, message: 'Server error during activation.' });
  }
});

// API: Desktop Client License Verification (Startup check)
app.post('/api/license/verify', async (req, res) => {
  try {
    const { username, license_key, machine_id } = req.body;

    if (!username || !license_key || !machine_id) {
      return res.status(400).json({ success: false, message: 'Username, license key, and machine ID are required.' });
    }

    const result = await db.verifyLicense(username, license_key, machine_id);
    res.json(result);
  } catch (error) {
    console.error('License verification error:', error);
    res.status(500).json({ success: false, message: 'Server error during verification.' });
  }
});

// API: Desktop Client License Logout (Deactivates machine ID)
app.post('/api/license/logout', async (req, res) => {
  try {
    const { username, license_key, machine_id } = req.body;

    if (!username || !license_key || !machine_id) {
      return res.status(400).json({ success: false, message: 'Username, license key, and machine ID are required.' });
    }

    const result = await db.logoutLicense(username, license_key, machine_id);
    res.json(result);
  } catch (error) {
    console.error('License logout error:', error);
    res.status(500).json({ success: false, message: 'Server error during logout.' });
  }
});

// Route: Download zip files from workspace root
app.get('/download/:filename', (req, res) => {
  const filename = req.params.filename;
  // Prevent path traversal attacks
  if (filename.includes('..') || filename.includes('/') || filename.includes('\\')) {
    return res.status(403).send('Access Denied');
  }

  const rootPath = path.resolve(__dirname, '..');
  const filePath = path.join(rootPath, filename);

  if (fs.existsSync(filePath) && (filename.endsWith('.zip') || filename.endsWith('.exe') || filename.endsWith('.dmg') || filename.endsWith('.app'))) {
    res.download(filePath);
  } else {
    // If not in root, look in server folder just in case
    const localPath = path.join(__dirname, filename);
    if (fs.existsSync(localPath)) {
      res.download(localPath);
    } else {
      res.status(404).send(`File '${filename}' not found. Please place your product zip files (e.g. VeloLeads.zip) in the root of the project directory.`);
    }
  }
});

// Catch-all route for static serving (redirect to home page)
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// Start Server
app.listen(PORT, () => {
  console.log(`==================================================`);
  console.log(`VeloLeads Licensing Portal running on port ${PORT}`);
  console.log(`Access the website at: http://localhost:${PORT}`);
  console.log(`==================================================`);
});
