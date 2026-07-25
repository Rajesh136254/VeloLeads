# VeloLeads Licensing Portal

This is the licensing backend and landing page for **VeloLeads**.

## Tech Stack
- **Frontend**: Vanilla HTML5, CSS3, ES6 JavaScript, Google Fonts (Outfit & Inter), FontAwesome icons, Razorpay Checkout SDK.
- **Backend**: Node.js, Express.js.
- **Database**: SQLite3 (persistent local database).

## Features
1. **Interactive SaaS Landing Page**: Modern, responsive landing page showing features, app preview, and ₹999/year pricing plan.
2. **Double-Registration Prevention**: Verifies that a target email and username is unique before starting the payment.
3. **Razorpay Integration**: Creates payment orders on the server and verifies signatures on success.
4. **License Generator**: Generates secure activation keys like `VELO-XXXX-XXXX-XXXX` upon successful verification.
5. **App Download Serving**: Serves the standalone operating system ZIP files directly from the parent directory of this server.
6. **Device Activation Check**: Binds the username and license key to a single unique `machine_id` (hardware ID).

## Setup & Running Locally

1. Open a terminal in this directory:
   ```bash
   cd c:\Users\rajes\Desktop\VeloLeads\server
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Run the server:
   ```bash
   npm start
   ```

4. Open your browser and navigate to:
   [http://localhost:5000](http://localhost:5000)

## Deployment

You can deploy this server to **Render**, **Railway**, or **Fly.io** in a single click:
1. Push this folder to a GitHub repository.
2. Link the repository to your hosting service (e.g. Render Web Service).
3. Set your environment variables on the dashboard:
   - `RAZORPAY_KEY_ID`: Your Razorpay Key ID
   - `RAZORPAY_KEY_SECRET`: Your Razorpay Key Secret
   - `PORT`: 5000 (Render sets this automatically)
4. Ensure your product zip files (`VeloLeads_Windows.zip` and `VeloLeads_Mac.zip`) are placed in the root folder of the project repository so the server can serve them for downloads.
